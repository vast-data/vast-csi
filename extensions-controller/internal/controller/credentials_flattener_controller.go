package controller

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
)

const (
	credentialsSecretNameIndex = "spec.credentialsSecretName"
	requeueAfter               = 15 * time.Second

	eventReasonFlattenError  = "FlattenError"
	eventReasonForeignClash  = "FlattenForeignClash"
	eventReasonMissingSecret = "FlattenWaitingSecret"

	// controller-runtime name and Kubernetes Event source for this reconciler.
	credentialsFlattenerControllerName = "cosi-credentials-flattener"
)

// errForeignFlat means *-flat exists but is not owned by this BucketAccess.
// Returned from CreateOrUpdate TOCTOU guard in ensureFlat*.
var errForeignFlat = errors.New("foreign flat object")

// CredentialsFlattenerReconciler flattens COSI BucketInfo Secrets into Rook-style env vars.
type CredentialsFlattenerReconciler struct {
	client.Client
	Scheme   *runtime.Scheme
	Recorder record.EventRecorder

	// eventOnce dedupes Warning/Normal Events that would otherwise fire on every
	// 15s requeue (missing Secret, bad JSON, foreign clash). Key = ns/name,
	// value = reason|message of the last Event we emitted.
	//
	// Process-local only: restart → one extra Event is fine. Success path clears
	// the entry so the next failure Events again.
	eventOnceMu sync.Mutex
	eventOnce   map[types.NamespacedName]string
}

// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketaccesses,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

func (r *CredentialsFlattenerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	ba := &objectstoragev1alpha1.BucketAccess{}
	if err := r.Get(ctx, req.NamespacedName, ba); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	if !cosi.WantFlatten(ba.GetAnnotations()) {
		if err := r.deleteOwnedFlatPair(ctx, ba, ""); err != nil {
			return ctrl.Result{}, err
		}
		r.clearEventOnce(ba)
		return ctrl.Result{}, nil
	}

	credName := ba.Spec.CredentialsSecretName
	if credName == "" {
		r.eventDeduped(ba, corev1.EventTypeWarning, eventReasonFlattenError, "credentialsSecretName is empty")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}
	flatName := cosi.FlatName(credName)

	// Rename cleanup: drop owned -flat siblings that are not the current flat name.
	if err := r.deleteOwnedFlatPair(ctx, ba, flatName); err != nil {
		return ctrl.Result{}, err
	}

	src := &corev1.Secret{}
	if err := r.Get(ctx, types.NamespacedName{Namespace: ba.Namespace, Name: credName}, src); err != nil {
		if apierrors.IsNotFound(err) {
			logger.Info("source credentials Secret missing; requeue", "secret", credName)
			// Deduped: without this we Event every 15s while waiting for COSI sidecar.
			r.eventDeduped(ba, corev1.EventTypeNormal, eventReasonMissingSecret, fmt.Sprintf("waiting for Secret %q", credName))
			return ctrl.Result{RequeueAfter: requeueAfter}, nil
		}
		return ctrl.Result{}, err
	}

	raw, ok := src.Data[cosi.BucketInfoKey]
	if !ok {
		r.eventDeduped(ba, corev1.EventTypeWarning, eventReasonFlattenError, "Secret missing BucketInfo key")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}
	data, err := cosi.ParseBucketInfo(raw)
	if err != nil {
		logger.Error(err, "BucketInfo parse failed; keeping last-good -flat if any")
		// Deduped: bad JSON can sit for a long time; Event once, then log-only via logger above on repeats.
		r.eventDeduped(ba, corev1.EventTypeWarning, eventReasonFlattenError, err.Error())
		// Keep last-good owned -flat untouched.
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	if err := r.ensureFlatPair(ctx, ba, flatName, data); err != nil {
		if errors.Is(err, errForeignFlat) {
			// Must RequeueAfter: foreign *-flat is not credentialsSecretName, so the
			// Secret→BA watch never fires when the foreign object is later deleted.
			return r.reconcileForeignClash(ba, flatName), nil
		}
		return ctrl.Result{}, err
	}

	// Success: allow a future failure to Event again with a fresh message.
	r.clearEventOnce(ba)
	return ctrl.Result{}, nil
}

func (r *CredentialsFlattenerReconciler) event(ba *objectstoragev1alpha1.BucketAccess, eventType, reason, msg string) {
	if r.Recorder != nil {
		r.Recorder.Event(ba, eventType, reason, msg)
	}
}

// eventDeduped emits an Event only when reason+msg changed since the last emit for this BA.
func (r *CredentialsFlattenerReconciler) eventDeduped(ba *objectstoragev1alpha1.BucketAccess, eventType, reason, msg string) {
	key := types.NamespacedName{Namespace: ba.Namespace, Name: ba.Name}
	stamp := reason + "|" + msg

	r.eventOnceMu.Lock()
	if r.eventOnce == nil {
		r.eventOnce = map[types.NamespacedName]string{}
	}
	if r.eventOnce[key] == stamp {
		r.eventOnceMu.Unlock()
		return
	}
	r.eventOnce[key] = stamp
	r.eventOnceMu.Unlock()

	r.event(ba, eventType, reason, msg)
}

func (r *CredentialsFlattenerReconciler) clearEventOnce(ba *objectstoragev1alpha1.BucketAccess) {
	key := types.NamespacedName{Namespace: ba.Namespace, Name: ba.Name}
	r.eventOnceMu.Lock()
	delete(r.eventOnce, key)
	r.eventOnceMu.Unlock()
}

func (r *CredentialsFlattenerReconciler) reconcileForeignClash(ba *objectstoragev1alpha1.BucketAccess, flatName string) ctrl.Result {
	r.eventDeduped(ba, corev1.EventTypeWarning, eventReasonForeignClash,
		fmt.Sprintf("%q already exists and is not owned by this BucketAccess", flatName))
	return ctrl.Result{RequeueAfter: requeueAfter}
}

func isOwnedBy(obj metav1.Object, ba *objectstoragev1alpha1.BucketAccess) bool {
	for _, ref := range obj.GetOwnerReferences() {
		if ref.UID == ba.UID && ref.Controller != nil && *ref.Controller {
			return true
		}
	}
	return false
}

// ensureFlatPair writes the *-flat Secret and ConfigMap together. On ConfigMap
// failure after Secret success, rolls back the owned flat Secret so clients never
// see credentials without matching BUCKET_* env vars.
func (r *CredentialsFlattenerReconciler) ensureFlatPair(ctx context.Context, ba *objectstoragev1alpha1.BucketAccess, flatName string, data cosi.FlatData) error {
	if err := r.ensureFlatSecret(ctx, ba, flatName, data); err != nil {
		return err
	}
	if err := r.ensureFlatConfigMap(ctx, ba, flatName, data); err != nil {
		if rbErr := r.rollbackFlatSecret(ctx, ba, flatName); rbErr != nil {
			return fmt.Errorf("ensure flat ConfigMap: %w (rollback Secret: %v)", err, rbErr)
		}
		return err
	}
	return nil
}

func (r *CredentialsFlattenerReconciler) rollbackFlatSecret(ctx context.Context, ba *objectstoragev1alpha1.BucketAccess, flatName string) error {
	sec := &corev1.Secret{}
	if err := r.Get(ctx, types.NamespacedName{Namespace: ba.Namespace, Name: flatName}, sec); err != nil {
		if apierrors.IsNotFound(err) {
			return nil
		}
		return err
	}
	if !isOwnedBy(sec, ba) {
		return nil
	}
	if err := r.Delete(ctx, sec); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	return nil
}

// deleteOwnedFlatPair deletes Secrets/ConfigMaps labeled for this BA.
// If keepName is non-empty, that name is preserved.
func (r *CredentialsFlattenerReconciler) deleteOwnedFlatPair(ctx context.Context, ba *objectstoragev1alpha1.BucketAccess, keepName string) error {
	sel := client.MatchingLabels{cosi.LabelBucketAccessUID: string(ba.UID)}

	secList := &corev1.SecretList{}
	if err := r.List(ctx, secList, client.InNamespace(ba.Namespace), sel); err != nil {
		return err
	}
	for i := range secList.Items {
		sec := &secList.Items[i]
		if !isOwnedBy(sec, ba) {
			continue
		}
		if keepName != "" && sec.Name == keepName {
			continue
		}
		if err := r.Delete(ctx, sec); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}

	cmList := &corev1.ConfigMapList{}
	if err := r.List(ctx, cmList, client.InNamespace(ba.Namespace), sel); err != nil {
		return err
	}
	for i := range cmList.Items {
		cm := &cmList.Items[i]
		if !isOwnedBy(cm, ba) {
			continue
		}
		if keepName != "" && cm.Name == keepName {
			continue
		}
		if err := r.Delete(ctx, cm); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}
	return nil
}

func (r *CredentialsFlattenerReconciler) ensureFlatSecret(ctx context.Context, ba *objectstoragev1alpha1.BucketAccess, flatName string, data cosi.FlatData) error {
	sec := &corev1.Secret{ObjectMeta: metav1.ObjectMeta{Name: flatName, Namespace: ba.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, sec, func() error {
		// TOCTOU: between Get and mutate another client can create a Secret with the same name and no
		// controller owner. SetControllerReference would then *adopt* it and we
		// would overwrite its data — design says never adopt/overwrite foreign.
		// UID != "" means the object already existed when CreateOrUpdate loaded it.
		if sec.UID != "" && !isOwnedBy(sec, ba) {
			return errForeignFlat
		}
		if err := controllerutil.SetControllerReference(ba, sec, r.Scheme); err != nil {
			return err
		}
		metav1.SetMetaDataLabel(&sec.ObjectMeta, cosi.LabelBucketAccessUID, string(ba.UID))
		sec.Data = map[string][]byte{
			"AWS_ACCESS_KEY_ID":     []byte(data.AccessKeyID),
			"AWS_SECRET_ACCESS_KEY": []byte(data.SecretAccessKey),
		}
		return nil
	})
	return err
}

func (r *CredentialsFlattenerReconciler) ensureFlatConfigMap(ctx context.Context, ba *objectstoragev1alpha1.BucketAccess, flatName string, data cosi.FlatData) error {
	cm := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: flatName, Namespace: ba.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, cm, func() error {
		// Same TOCTOU guard as ensureFlatSecret (see comment there).
		if cm.UID != "" && !isOwnedBy(cm, ba) {
			return errForeignFlat
		}
		if err := controllerutil.SetControllerReference(ba, cm, r.Scheme); err != nil {
			return err
		}
		metav1.SetMetaDataLabel(&cm.ObjectMeta, cosi.LabelBucketAccessUID, string(ba.UID))
		cm.Data = map[string]string{
			"BUCKET_NAME":     data.BucketName,
			"BUCKET_HOST":     data.Host,
			"BUCKET_PORT":     data.Port,
			"BUCKET_ENDPOINT": data.Endpoint,
		}
		return nil
	})
	return err
}

// SetupCredentialsFlattenerController registers the COSI credentials flattener (BucketAccess → *-flat).
func SetupCredentialsFlattenerController(mgr ctrl.Manager) error {
	r := &CredentialsFlattenerReconciler{
		Client:   mgr.GetClient(),
		Scheme:   mgr.GetScheme(),
		Recorder: mgr.GetEventRecorderFor(credentialsFlattenerControllerName),
	}

	if err := mgr.GetFieldIndexer().IndexField(
		context.Background(),
		&objectstoragev1alpha1.BucketAccess{},
		credentialsSecretNameIndex,
		func(obj client.Object) []string {
			ba := obj.(*objectstoragev1alpha1.BucketAccess)
			if ba.Spec.CredentialsSecretName == "" {
				return nil
			}
			return []string{ba.Spec.CredentialsSecretName}
		},
	); err != nil {
		return err
	}

	mapSecretToBA := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
		var list objectstoragev1alpha1.BucketAccessList
		if err := r.List(ctx, &list,
			client.InNamespace(obj.GetNamespace()),
			client.MatchingFields{credentialsSecretNameIndex: obj.GetName()},
		); err != nil {
			log.FromContext(ctx).Error(err, "list BucketAccess for Secret enqueue failed",
				"secret", obj.GetName(), "namespace", obj.GetNamespace())
			return nil
		}
		reqs := make([]reconcile.Request, 0, len(list.Items))
		for i := range list.Items {
			reqs = append(reqs, reconcile.Request{
				NamespacedName: types.NamespacedName{
					Namespace: list.Items[i].Namespace,
					Name:      list.Items[i].Name,
				},
			})
		}
		return reqs
	})

	// Skip *-flat Secrets on the secondary watch: those are our outputs (Owns already
	// enqueues their BA). Without this, every flat update wakes mapFn for no benefit
	// and adds API noise on busy clusters.
	ignoreFlatSecrets := predicate.NewPredicateFuncs(func(obj client.Object) bool {
		return !strings.HasSuffix(obj.GetName(), "-flat")
	})

	return ctrl.NewControllerManagedBy(mgr).
		For(&objectstoragev1alpha1.BucketAccess{}).
		Owns(&corev1.Secret{}).
		Owns(&corev1.ConfigMap{}).
		Watches(&corev1.Secret{}, mapSecretToBA, builder.WithPredicates(ignoreFlatSecrets), builder.OnlyMetadata).
		Named(credentialsFlattenerControllerName).
		Complete(r)
}
