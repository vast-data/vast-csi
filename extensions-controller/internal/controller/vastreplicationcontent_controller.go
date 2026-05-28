/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"fmt"

	"go.uber.org/zap"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	k8sruntime "k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/util/retry"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/provisioner"
)

// VastReplicationContentReconciler reconciles VastReplicationContent objects.
//
// # Each VastReplicationContent manages the lifecycle of one StorageClass
//
// All data needed by the provisioner is carried in the VastReplicationContent
// spec (PVCs, ReplicationPath, ProtectionPolicyName, ProtectedPathName).
// The reconciler constructs a minimal VolumeReplication or
// VolumeGroupReplication object from those spec fields.
// ProtectionPolicyName is read from the newly-created mirrored VR/VGR and
// stored in the status so that snapshot cleanup can proceed even if the
// mirrored object is later deleted.
type VastReplicationContentReconciler struct {
	BaseReconciler
}

// +kubebuilder:rbac:groups=vastdata.com,resources=vastreplicationcontents,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=vastdata.com,resources=vastreplicationcontents/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=vastdata.com,resources=vastreplicationcontents/finalizers,verbs=update
// +kubebuilder:rbac:groups="",resources=persistentvolumeclaims,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=persistentvolumes,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=secrets,verbs=get;list;watch

func (r *VastReplicationContentReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	bo := r.BackoffFor(req.NamespacedName)

	vrc, err := r.K8sClient.GetVastReplicationContent(ctx, req.Name, req.Namespace)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	log := r.LogFor("vrc", vrcLoggerName(vrc))
	k8s := r.K8sFor(log)
	emit := r.EmitFor(ctx, log, vrc)

	// Propagate every event emitted on this VRC to its owning parent (VVR or
	// VSCR) so that the parent's event stream reflects child activity.
	parent, err := r.lookupVRCParent(ctx, vrc, k8s)
	if err != nil {
		return r.maybeBackoffRetry(bo, fmt.Errorf("resolve VRC parent: %w", err), log)
	}
	emit = emit.Bind(parent)

	log.Info("=== reconciling VastReplicationContent ===",
		zap.String("kind", vrc.Spec.Kind),
		zap.String("storageClass", vrc.Spec.StorageClass),
		zap.String("pvcs", vrc.Spec.PVCs.String()))

	if vrc.GetDeletionTimestamp() != nil {
		if vrc.Annotations[common.AnnotationCleanupDone] != "true" {
			// Wait for the parent VGR/VR to be fully gone before running any
			// cleanup.  csi-addons' cleanupGroupPVC needs the mirror PVCs to
			// exist while it processes the terminating VGR; if we delete them
			// first, csi-addons errors and can never remove its vgr-protection
			// finalizer, leaving the VGR stuck forever.
			parentGone, err := r.parentIsFullyGone(ctx, vrc, k8s)
			if err != nil {
				return ctrl.Result{}, err
			}
			if !parentGone {
				next := bo.Next()
				if unblocked, err := r.unblockParentDeletion(ctx, vrc, k8s); err != nil {
					return ctrl.Result{}, fmt.Errorf("unblock parent deletion for VRC %s/%s: %w", vrc.Namespace, vrc.Name, err)
				} else if unblocked {
					return ctrl.Result{RequeueAfter: next}, nil
				}
				log.Info("waiting for parent VGR/VR to be fully deleted before running cleanup",
					zap.Duration("requeueAfter", next))
				return ctrl.Result{RequeueAfter: next}, nil
			}

			log.Info("VastReplicationContent is being deleted, cleaning up resources")
			if err := r.cleanResources(ctx, vrc, emit); err != nil {
				emit.Warningf(events.ReasonCleanupFailed, "cleanup failed: %v", err)
				return ctrl.Result{}, fmt.Errorf("failed to clean resources: %w", err)
			}
			emit.Normalf(
				events.ReasonCleanupSucceeded,
				"resources for VastReplicationContent %q cleaned up", req.NamespacedName.String(),
			)
			if err := k8s.SetAnnotationAndUpdate(ctx, vrc, common.AnnotationCleanupDone, "true"); err != nil {
				return ctrl.Result{}, err
			}
		}

		allDone, err := r.allVCRsDeleted(ctx, vrc)
		if err != nil {
			return ctrl.Result{}, err
		}
		if !allDone {
			next := bo.Next()
			log.Info("waiting for other constellation VastReplicationContents to finish cleanup before removing finalizer",
				zap.Duration("requeueAfter", next))
			return ctrl.Result{RequeueAfter: next}, nil
		}

		if err := k8s.RemoveFinalizer(ctx, vrc, common.FinalizerReplicationContent); err != nil {
			return ctrl.Result{}, err
		}
		bo.Reset()
		return ctrl.Result{}, nil
	}

	// Self-destruction: if the parent VGR/VR is gone or terminating this VRC
	// no longer has a reason to exist — delete it so the cleanup path runs.
	if gone, err := r.parentIsGoneOrTerminating(ctx, vrc, k8s); err != nil {
		return ctrl.Result{}, err
	} else if gone {
		log.Info("parent VGR/VR is gone or terminating, self-destructing VastReplicationContent")
		if err := k8s.DeleteVastReplicationContent(ctx, vrc); err != nil && !k8serrors.IsNotFound(err) {
			return ctrl.Result{}, fmt.Errorf("self-destruct VRC %s/%s: %w", vrc.Namespace, vrc.Name, err)
		}
		return ctrl.Result{}, nil
	}

	if err := r.provisionResources(ctx, vrc, k8s, emit); err != nil {
		emit.Warningf(events.ReasonProvisionFailed, "provisioning failed: %v", err)
		return r.maybeBackoffRetry(bo, err, log)
	}
	bo.Reset()
	return ctrl.Result{}, nil
}

// ---------------------------------------------------------------------------
// Provision
// ---------------------------------------------------------------------------

func (r *VastReplicationContentReconciler) provisionResources(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
) error {

	prov, err := provisioner.NewProvisioner(ctx, k8s, vrc, emit, r.Config)
	if err != nil {
		return err
	}

	// Sync observed generation and PVC metadata so status reflects current spec.
	if err := r.syncProvisionMeta(ctx, vrc, emit); err != nil {
		return err
	}

	if err := prov.ProvisionVolumes(ctx); err != nil {
		return err
	}

	return r.markProvisioned(ctx, vrc, k8s, emit)
}

// syncProvisionMeta updates ObservedGeneration, PVCsPreview and PVCs in the
// status to match the current spec.
func (r *VastReplicationContentReconciler) syncProvisionMeta(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	emit *events.BoundReporter,
) error {
	k8s := r.K8sFor(emit.Logger())
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		fresh, err := k8s.GetVastReplicationContent(ctx, vrc.Name, vrc.Namespace)
		if err != nil {
			return err
		}
		newPreview := fresh.Spec.PVCs.String()
		if fresh.Status.ObservedGeneration == fresh.Generation &&
			fresh.Status.PVCsPreview == newPreview &&
			fresh.Status.PVCs.Equal(fresh.Spec.PVCs) {
			return nil // already up to date
		}
		fresh.Status.ObservedGeneration = fresh.Generation
		fresh.Status.PVCsPreview = newPreview
		fresh.Status.PVCs = make(vastv1alpha1.PVCList, len(fresh.Spec.PVCs))
		copy(fresh.Status.PVCs, fresh.Spec.PVCs)
		return k8s.UpdateVastReplicationContentStatus(ctx, fresh)
	})
	if err != nil {
		emit.Warningf(events.ReasonStatusUpdateFailed, "failed to sync VastReplicationContent metadata: %v", err)
	}
	return nil
}

// markProvisioned sets Provisioned=true on the VastReplicationContent status.
func (r *VastReplicationContentReconciler) markProvisioned(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
) error {
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		fresh, err := k8s.GetVastReplicationContent(ctx, vrc.Name, vrc.Namespace)
		if err != nil {
			return err
		}
		if fresh.Status.Provisioned {
			return nil // already marked
		}
		fresh.Status.Provisioned = true
		return k8s.UpdateVastReplicationContentStatus(ctx, fresh)
	})
	if err != nil {
		emit.Warningf(events.ReasonStatusUpdateFailed, "failed to mark VastReplicationContent as provisioned: %v", err)
	}
	return nil
}

// allVCRsDeleted returns true when every peer VastReplicationContent in the
// same constellation has finished its own cleanup (AnnotationCleanupDone).
// Deletion of peer VRCs is driven by the ReplicationObjectReconciler, which
// explicitly deletes a VRC when its parent VGR/VR acquires a DeletionTimestamp.
func (r *VastReplicationContentReconciler) allVCRsDeleted(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
) (bool, error) {
	vrcs, err := vrc.GetConstellationVRCs(ctx, r.K8sClient.ListVastReplicationContentsByLabelSelector)
	if err != nil {
		return false, fmt.Errorf("list constellation VastReplicationContents: %w", err)
	}
	for _, other := range vrcs {
		if other.Name == vrc.Name {
			continue // don't wait on ourselves
		}
		if other.Annotations[common.AnnotationCleanupDone] != "true" {
			return false, nil
		}
	}
	return true, nil
}

// cleanResources finds all managed resources for this content's StorageClass
// via label selectors and deletes them.
func (r *VastReplicationContentReconciler) cleanResources(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	emit *events.BoundReporter,
) error {
	emit.Normalf(events.ReasonCleanupStarted,
		"cleaning %s resources for StorageClass %q (replicationPath=%q, protectionPolicy=%q)",
		vrc.Spec.Kind, vrc.Spec.StorageClass,
		vrc.Spec.ReplicationPath, vrc.Spec.ProtectionPolicyName)

	prov, err := provisioner.NewProvisioner(ctx, r.K8sFor(emit.Logger()), vrc, emit, r.Config)
	if err != nil {
		return err
	}
	return prov.CleanVolumes(ctx)
}

// unblockParentDeletion clears blockOwnerDeletion on the VGR/VR owner
// reference when the parent is terminating. Returns true when a patch was sent.
func (r *VastReplicationContentReconciler) unblockParentDeletion(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
) (bool, error) {
	terminating, err := r.parentIsTerminating(ctx, vrc, k8s)
	if err != nil || !terminating {
		return false, err
	}
	ownerKind := vrc.Spec.Kind
	var patched bool
	err = k8s.PatchWithRetry(ctx, vrc, func() {
		vrc.OwnerReferences, patched = clearParentBlockOwnerDeletion(vrc.OwnerReferences, ownerKind, vrc.Name)
	})
	if err != nil {
		return false, err
	}
	return patched, nil
}

// clearParentBlockOwnerDeletion sets blockOwnerDeletion=false on the owner ref
// that matches ownerKind/ownerName. Returns the (possibly) updated slice and
// whether any ref was changed.
func clearParentBlockOwnerDeletion(refs []metav1.OwnerReference, ownerKind, ownerName string) ([]metav1.OwnerReference, bool) {
	changed := false
	blockFalse := false
	for i := range refs {
		ref := &refs[i]
		if ref.Kind != ownerKind || ref.Name != ownerName {
			continue
		}
		if ref.BlockOwnerDeletion != nil && !*ref.BlockOwnerDeletion {
			continue
		}
		ref.BlockOwnerDeletion = &blockFalse
		changed = true
	}
	return refs, changed
}

// parentIsTerminating reports whether the mirrored VGR/VR exists and has a
// deletion timestamp.
func (r *VastReplicationContentReconciler) parentIsTerminating(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
) (bool, error) {
	switch vrc.Spec.Kind {
	case vastv1alpha1.DestinationKindVolumeGroupReplication:
		vgr, err := k8s.GetVolumeGroupReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return false, nil
		}
		if err != nil {
			return false, err
		}
		return vgr.GetDeletionTimestamp() != nil, nil
	case vastv1alpha1.DestinationKindVolumeReplication:
		vr, err := k8s.GetVolumeReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return false, nil
		}
		if err != nil {
			return false, err
		}
		return vr.GetDeletionTimestamp() != nil, nil
	default:
		return false, nil
	}
}

// parentIsFullyGone returns true only when the parent VGR/VR no longer exists
// at all (IsNotFound).  A parent that merely has a DeletionTimestamp is NOT
// yet "fully gone" — csi-addons may still be running its cleanupGroupPVC
// logic, which needs mirror PVCs to be present.
func (r *VastReplicationContentReconciler) parentIsFullyGone(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
) (bool, error) {
	switch vrc.Spec.Kind {
	case vastv1alpha1.DestinationKindVolumeGroupReplication:
		_, err := k8s.GetVolumeGroupReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return true, nil
		}
		return false, err
	case vastv1alpha1.DestinationKindVolumeReplication:
		_, err := k8s.GetVolumeReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return true, nil
		}
		return false, err
	}
	return true, nil
}

// parentIsGoneOrTerminating returns true when the VRC's parent VGR/VR no
// longer exists or has acquired a DeletionTimestamp, meaning this VRC should
// self-destruct.
func (r *VastReplicationContentReconciler) parentIsGoneOrTerminating(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
) (bool, error) {
	switch vrc.Spec.Kind {
	case vastv1alpha1.DestinationKindVolumeGroupReplication:
		vgr, err := k8s.GetVolumeGroupReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return true, nil
		}
		if err != nil {
			return false, err
		}
		return vgr.GetDeletionTimestamp() != nil, nil
	case vastv1alpha1.DestinationKindVolumeReplication:
		vr, err := k8s.GetVolumeReplication(ctx, vrc.Name, vrc.Namespace)
		if k8serrors.IsNotFound(err) {
			return true, nil
		}
		if err != nil {
			return false, err
		}
		return vr.GetDeletionTimestamp() != nil, nil
	}
	return false, nil
}

// SetupVastReplicationContentController registers the VastReplicationContentReconciler
// with the manager.
func SetupVastReplicationContentController(mgr ctrl.Manager, k8sClient *k8sclient.K8sClient, logger *zap.Logger, cfg *config.Config) error {
	base, err := NewBaseReconciler(mgr, k8sClient, logger, cfg, "vastreplicationcontent")
	if err != nil {
		return err
	}
	r := &VastReplicationContentReconciler{BaseReconciler: base}

	return ctrl.NewControllerManagedBy(mgr).
		For(&vastv1alpha1.VastReplicationContent{}, builder.WithPredicates(VastReplicationContentPredicate())).
		Complete(r)
}

// lookupVRCParent returns the VVR or VSCR that owns this VRC as a runtime.Object.
// Every VastReplicationContent must carry exactly one of LabelSourceVVR or
// LabelSourceVSCR — the absence of both is treated as a hard error.
func (r *VastReplicationContentReconciler) lookupVRCParent(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	k8s *k8sclient.K8sClient,
) (k8sruntime.Object, error) {
	if vvrName := vrc.Labels[common.LabelSourceVVR]; vvrName != "" {
		vvr, err := k8s.GetVastVolumeReplication(ctx, vvrName, vrc.Namespace)
		if err != nil {
			return nil, fmt.Errorf("lookup parent VVR %s/%s: %w", vrc.Namespace, vvrName, err)
		}
		return vvr, nil
	}
	if vscrName := vrc.Labels[common.LabelSourceVSCR]; vscrName != "" {
		vscr, err := k8s.GetVastStorageClassReplication(ctx, vscrName, vrc.Namespace)
		if err != nil {
			return nil, fmt.Errorf("lookup parent VSCR %s/%s: %w", vrc.Namespace, vscrName, err)
		}
		return vscr, nil
	}
	return nil, fmt.Errorf("VastReplicationContent %s/%s has neither %s nor %s label",
		vrc.Namespace, vrc.Name, common.LabelSourceVVR, common.LabelSourceVSCR)
}

// vrcLoggerName returns a short named-logger identifier for the VRC, e.g.
// "vgr/default/myapp-volume-group-repl-16-0-0-2" or "vg/default/myapp-volume-group".
func vrcLoggerName(vrc *vastv1alpha1.VastReplicationContent) string {
	var kind string
	switch vrc.Spec.Kind {
	case vastv1alpha1.DestinationKindVolumeGroupReplication:
		kind = "vgr"
	case vastv1alpha1.DestinationKindVolumeReplication:
		kind = "vr"
	default:
		kind = "vrc"
	}
	return fmt.Sprintf("%s/%s/%s", kind, vrc.Namespace, vrc.Name)
}
