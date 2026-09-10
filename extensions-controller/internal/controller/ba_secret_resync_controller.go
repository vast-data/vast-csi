package controller

import (
	"context"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

const (
	baResyncBucketClaimIndex = "baSecretResync.spec.bucketClaimName"

	baSecretResyncControllerName = "cosi-ba-secret-resync"

	eventReasonBucketSecretMismatch = "BucketSecretMismatch"
	eventReasonBucketInfoParseError = "BucketInfoParseError"
)

// BucketAccessSecretResyncReconciler pokes the stock COSI sidecar when a
// BucketAccess credentials Secret still names an old bucket after the
// BucketClaim was recreated under the same name.
//
// It never writes BucketInfo. cosi.PokeSidecarRegrant invalidates the credentials
// bundle and clears BA grant status so objectstorage-sidecar re-runs Grant.
//
// Watches BucketClaim: ticket trigger is claim recreate → new status.bucketName.
// BA primary watch covers status/spec changes.
type BucketAccessSecretResyncReconciler struct {
	K8s      *k8s_client.K8sClient
	Recorder record.EventRecorder
}

// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketaccesses,verbs=get;list;watch
// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketaccesses/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketclaims,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;delete
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

func (r *BucketAccessSecretResyncReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	c := r.K8s.Client()

	ba := &objectstoragev1alpha1.BucketAccess{}
	if err := c.Get(ctx, req.NamespacedName, ba); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}
	if !ba.GetDeletionTimestamp().IsZero() {
		return ctrl.Result{}, nil
	}
	if !ba.Status.AccessGranted || ba.Status.AccountID == "" {
		return ctrl.Result{}, nil
	}

	claimName := ba.Spec.BucketClaimName
	credName := ba.Spec.CredentialsSecretName
	if claimName == "" || credName == "" {
		return ctrl.Result{}, nil
	}

	claim := &objectstoragev1alpha1.BucketClaim{}
	if err := c.Get(ctx, types.NamespacedName{Namespace: ba.Namespace, Name: claimName}, claim); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}
	if !claim.Status.BucketReady || claim.Status.BucketName == "" {
		return ctrl.Result{}, nil
	}

	sec := &corev1.Secret{}
	err := c.Get(ctx, types.NamespacedName{Namespace: ba.Namespace, Name: credName}, sec)
	if apierrors.IsNotFound(err) {
		// Secret already gone (prior poke deleted it; status clear may still be pending).
		logger.Info("credentials Secret missing while AccessGranted; poking sidecar re-grant",
			"secret", credName)
		return ctrl.Result{}, cosi.PokeSidecarRegrant(ctx, r.K8s, ba, nil)
	}
	if err != nil {
		return ctrl.Result{}, err
	}

	raw, ok := sec.Data[cosi.BucketInfoKey]
	if !ok {
		return ctrl.Result{}, nil
	}
	info, err := cosi.ParseBucketInfo(raw)
	if err != nil {
		logger.Error(err, "BucketInfo parse failed; not poking")
		r.Recorder.Event(ba, corev1.EventTypeWarning, eventReasonBucketInfoParseError, err.Error())
		return ctrl.Result{}, nil
	}
	if info.BucketName == claim.Status.BucketName {
		return ctrl.Result{}, nil
	}

	logger.Info("credentials Secret bucket mismatch; poking sidecar re-grant",
		"secretBucket", info.BucketName,
		"claimBucket", claim.Status.BucketName,
		"secret", credName,
	)

	if err := cosi.PokeSidecarRegrant(ctx, r.K8s, ba, sec); err != nil {
		return ctrl.Result{}, err
	}

	r.Recorder.Event(ba, corev1.EventTypeWarning, eventReasonBucketSecretMismatch,
		fmt.Sprintf("Secret %q bucket %q != claim bucket %q; poked sidecar re-grant (invalidated credentials bundle, cleared accessGranted)",
			credName, info.BucketName, claim.Status.BucketName))
	return ctrl.Result{}, nil
}

// SetupBucketAccessSecretResyncController registers the BA↔claim mismatch poke reconciler.
func SetupBucketAccessSecretResyncController(mgr ctrl.Manager, k8s *k8s_client.K8sClient) error {
	r := &BucketAccessSecretResyncReconciler{
		K8s:      k8s,
		Recorder: mgr.GetEventRecorderFor(baSecretResyncControllerName),
	}

	if err := mgr.GetFieldIndexer().IndexField(
		context.Background(),
		&objectstoragev1alpha1.BucketAccess{},
		baResyncBucketClaimIndex,
		func(obj client.Object) []string {
			ba := obj.(*objectstoragev1alpha1.BucketAccess)
			if ba.Spec.BucketClaimName == "" {
				return nil
			}
			return []string{ba.Spec.BucketClaimName}
		},
	); err != nil {
		return err
	}

	mapClaimToBA := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
		var list objectstoragev1alpha1.BucketAccessList
		if err := r.K8s.Client().List(ctx, &list,
			client.InNamespace(obj.GetNamespace()),
			client.MatchingFields{baResyncBucketClaimIndex: obj.GetName()},
		); err != nil {
			log.FromContext(ctx).Error(err, "list BucketAccess for BucketClaim enqueue failed",
				"claim", obj.GetName(), "namespace", obj.GetNamespace())
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

	return ctrl.NewControllerManagedBy(mgr).
		For(&objectstoragev1alpha1.BucketAccess{}).
		Watches(&objectstoragev1alpha1.BucketClaim{}, mapClaimToBA).
		Named(baSecretResyncControllerName).
		Complete(r)
}
