package controller

import (
	"context"
	"errors"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/tools/record"
	"k8s.io/client-go/util/retry"
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
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

const (
	bucketClaimStatusHealControllerName = "cosi-bucketclaim-status-heal"

	eventReasonClaimStatusHealed  = "BucketClaimStatusHealed"
	eventReasonClaimHealAmbiguous = "BucketClaimHealAmbiguous"
)

// BucketClaimStatusHealReconciler fills status.bucketName (and the stock
// protection finalizer) when stock COSI leaves a claim as bucketReady=true
// with an empty bucketName — a known controller/sidecar dual-writer race under
// parallel BucketClaim create.
//
// Fill-only: never clears bucketReady, never overwrites a non-empty bucketName,
// never invents a name without exactly one matching Bucket (spec.bucketClaim
// name+namespace+UID). Bucket.status.bucketReady is not required. When the Bucket
// is not visible yet, reconcile returns without requeue; the Bucket watch
// enqueues the claim once it exists. Also restores the stock protection finalizer
// when ready && name already set but the finalizer is missing.
type BucketClaimStatusHealReconciler struct {
	K8s      *k8s_client.K8sClient
	Recorder record.EventRecorder
}

// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketclaims,verbs=get;list;watch;update
// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=bucketclaims/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=objectstorage.k8s.io,resources=buckets,verbs=get;list;watch
// +kubebuilder:rbac:groups="",resources=events,verbs=create;patch

func (r *BucketClaimStatusHealReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)
	c := r.K8s.Client()

	claim := &objectstoragev1alpha1.BucketClaim{}
	if err := c.Get(ctx, req.NamespacedName, claim); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}
	if !claim.GetDeletionTimestamp().IsZero() || !claim.Status.BucketReady {
		return ctrl.Result{}, nil
	}

	needName := claim.Status.BucketName == ""
	needFinalizer := !controllerutil.ContainsFinalizer(claim, cosi.BucketClaimProtectionFinalizer)
	if !needName && !needFinalizer {
		return ctrl.Result{}, nil
	}

	var healedName string
	if needName {
		bucket, err := r.K8s.FindCOSIBucketForClaim(ctx, claim)
		if err != nil {
			if errors.Is(err, k8s_client.ErrCOSIBucketNotFound) {
				logger.V(1).Info("claim ready without bucketName; waiting for Bucket watch",
					"claim", req.NamespacedName)
				return ctrl.Result{}, nil
			}
			if errors.Is(err, k8s_client.ErrCOSIBucketAmbiguous) {
				logger.Error(err, "refusing claim status heal")
				r.Recorder.Event(claim, corev1.EventTypeWarning, eventReasonClaimHealAmbiguous, err.Error())
				return ctrl.Result{}, nil
			}
			return ctrl.Result{}, err
		}
		healedName = bucket.Name
		if err := r.fillClaimBucketName(ctx, req, healedName); err != nil {
			return ctrl.Result{}, err
		}
		// Fresh Get so EnsureFinalizer mutates current metadata/RV.
		if err := c.Get(ctx, req.NamespacedName, claim); err != nil {
			return ctrl.Result{}, err
		}
	}

	if !controllerutil.ContainsFinalizer(claim, cosi.BucketClaimProtectionFinalizer) {
		if _, err := r.K8s.EnsureFinalizer(ctx, claim, cosi.BucketClaimProtectionFinalizer); err != nil {
			return ctrl.Result{}, err
		}
	}

	if healedName != "" {
		logger.Info("healed BucketClaim status from Bucket",
			"claim", req.NamespacedName, "bucketName", healedName)
		r.Recorder.Event(claim, corev1.EventTypeNormal, eventReasonClaimStatusHealed,
			fmt.Sprintf("set status.bucketName=%q from Bucket (stock COSI ready-without-name race)", healedName))
	} else {
		logger.Info("restored BucketClaim protection finalizer",
			"claim", req.NamespacedName, "bucketName", claim.Status.BucketName)
	}
	return ctrl.Result{}, nil
}

func (r *BucketClaimStatusHealReconciler) fillClaimBucketName(ctx context.Context, req ctrl.Request, bucketName string) error {
	c := r.K8s.Client()
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		claim := &objectstoragev1alpha1.BucketClaim{}
		if err := c.Get(ctx, req.NamespacedName, claim); err != nil {
			return err
		}
		if !claim.Status.BucketReady || claim.Status.BucketName != "" {
			return nil
		}
		claim.Status.BucketName = bucketName
		return c.Status().Update(ctx, claim)
	})
}

// bucketClaimNeedsStatusHeal gates primary BucketClaim events so healthy claims
// do not enqueue under parallel-create storms. Bucket→claim watches stay unfiltered
// so a newly visible Bucket can still wake a stuck claim.
func bucketClaimNeedsStatusHeal(obj client.Object) bool {
	claim, ok := obj.(*objectstoragev1alpha1.BucketClaim)
	if !ok {
		return false
	}
	if !claim.GetDeletionTimestamp().IsZero() || !claim.Status.BucketReady {
		return false
	}
	if claim.Status.BucketName == "" {
		return true
	}
	return !controllerutil.ContainsFinalizer(claim, cosi.BucketClaimProtectionFinalizer)
}

// SetupBucketClaimStatusHealController registers the ready-without-name heal reconciler.
// COSI Bucket indexes must already be registered (RegisterCOSIIndexes).
func SetupBucketClaimStatusHealController(mgr ctrl.Manager, k8s *k8s_client.K8sClient) error {
	r := &BucketClaimStatusHealReconciler{
		K8s:      k8s,
		Recorder: mgr.GetEventRecorderFor(bucketClaimStatusHealControllerName),
	}

	mapBucketToClaim := handler.EnqueueRequestsFromMapFunc(func(ctx context.Context, obj client.Object) []reconcile.Request {
		bucket, ok := obj.(*objectstoragev1alpha1.Bucket)
		if !ok {
			return nil
		}
		key := k8s_client.ClaimKeyFromBucket(bucket)
		if key.Name == "" || key.Namespace == "" {
			return nil
		}
		return []reconcile.Request{{NamespacedName: key}}
	})

	return ctrl.NewControllerManagedBy(mgr).
		For(&objectstoragev1alpha1.BucketClaim{}, builder.WithPredicates(predicate.NewPredicateFuncs(bucketClaimNeedsStatusHeal))).
		Watches(&objectstoragev1alpha1.Bucket{}, mapBucketToClaim).
		Named(bucketClaimStatusHealControllerName).
		Complete(r)
}
