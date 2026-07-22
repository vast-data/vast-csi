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
	"sort"
	"strings"
	"time"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/go-vast-client/resources/typed/expr"
	"go.uber.org/zap"
	storagev1 "k8s.io/api/storage/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/backoff"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
)

// Request-name prefixes used to route VR vs VGR events through the shared queue.
const (
	vrPrefix  = "vr/"
	vgrPrefix = "vgr/"
)

// ReplicationObjectReconciler watches VolumeReplication and VolumeGroupReplication
// objects that are owned by VastStorageClassReplication or VastVolumeReplication.
//
// For each such object it creates (or keeps in sync) exactly one counterpart.
// Kubernetes GC cascades deletion automatically; the VastReplicationContentReconciler
// then handles the VAST-side cleanup.
type ReplicationObjectReconciler struct {
	BaseReconciler
}

func (r *ReplicationObjectReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	name := req.Name
	ns := req.Namespace
	bo := r.BackoffFor(req.NamespacedName)

	var err error
	switch {
	case strings.HasPrefix(name, vrPrefix):
		err = r.reconcileVR(ctx, strings.TrimPrefix(name, vrPrefix), ns, bo)
	case strings.HasPrefix(name, vgrPrefix):
		err = r.reconcileVGR(ctx, strings.TrimPrefix(name, vgrPrefix), ns, bo)
	default:
		r.Log.Error("unexpected reconcile request without type prefix, ignoring",
			zap.String("name", name), zap.String("namespace", ns))
		return ctrl.Result{}, nil
	}

	return r.maybeBackoffRetry(bo, err, r.Log)
}

// reconcileVR ensures a Self VastReplicationContent exists for the given
// VolumeReplication (which must be owned by a VastVolumeReplication).
func (r *ReplicationObjectReconciler) reconcileVR(ctx context.Context, name, ns string, bo *backoff.BoundBackoff) error {
	log := r.LogFor("vr", ns+"/"+name)
	k8s := r.K8sFor(log)

	vr, err := k8s.GetVolumeReplication(ctx, name, ns)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return nil
		}
		return err
	}

	log.Info("=== reconciling VolumeReplication ===")
	emit := r.EmitFor(ctx, log, vr)

	if vr.GetDeletionTimestamp() != nil {
		vrc, err := k8s.GetVastReplicationContent(ctx, name, ns)
		if err != nil && !k8serrors.IsNotFound(err) {
			return fmt.Errorf("get VRC for terminating VR %s/%s: %w", ns, name, err)
		}
		if err == nil && vrc.GetDeletionTimestamp() == nil {
			log.Info("VolumeReplication is being deleted, deleting associated VastReplicationContent",
				zap.String("vrc", vrc.Name))
			if err := k8s.DeleteVastReplicationContent(ctx, vrc); err != nil {
				return fmt.Errorf("delete VRC for terminating VR %s/%s: %w", ns, name, err)
			}
		}
		return nil
	}

	pvcs := vastv1alpha1.PVCList{vr.Spec.DataSource.Name}
	newState := currentStateStr(vr.Status.State)

	sourceSCName := vr.Labels[common.LabelStorageClass]
	if sourceSCName == "" {
		return fmt.Errorf("VolumeReplication %s/%s is missing required label %q", ns, name, common.LabelStorageClass)
	}
	sourceSC, err := k8s.GetStorageClass(ctx, sourceSCName)
	if err != nil {
		return fmt.Errorf("failed to get StorageClass %s: %w", sourceSCName, err)
	}

	ownerVVR := common.OwnerByKind(vr.OwnerReferences, "VastVolumeReplication")
	if ownerVVR == nil {
		return fmt.Errorf("VolumeReplication %s/%s has no VastVolumeReplication owner reference", ns, name)
	}

	vvr, err := k8s.GetVastVolumeReplication(ctx, ownerVVR.Name, ns)
	if err != nil {
		return fmt.Errorf("failed to get VastVolumeReplication %s/%s: %w", ns, ownerVVR.Name, err)
	}

	provType := vastv1alpha1.ProvisionerTypeFile
	if k8sclient.IsBlockStorageClass(sourceSC) {
		provType = vastv1alpha1.ProvisionerTypeBlock
	}
	vrcLabels := map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
		common.LabelSourceVVR: ownerVVR.Name,
	}

	existing, err := k8s.GetVastReplicationContent(ctx, name, ns)
	if err != nil {
		if !k8serrors.IsNotFound(err) {
			return fmt.Errorf("failed to get VRC for VR %s/%s: %w", ns, name, err)
		}
		// First time: all immutable fields (including ppath) must be set at creation.
		ppath, err := resolveSourcePPath(ctx, k8s, sourceSC, r.Config.SSLVerify, log, vvr.Status.PpathName)
		if err != nil {
			if retryErr := handlePPathNetworkError(err, bo); retryErr != nil {
				return retryErr
			}
			return fmt.Errorf("VR %s/%s: %w", ns, name, err)
		}
		vrc := r.buildContent(sourceSCName, vastv1alpha1.DestinationKindVolumeReplication, name, ns, pvcs, vrcLabels)
		vrc.Spec.SyncPVCPV = true // VVR always requires mirror PVCs for csi-addons VolumeReplication
		vrc.Spec.ProvisionerType = provType
		vrc.Spec.ReplicationState = initialStateFromPrimary(newState, sourceSCName, vvr.Spec.PrimaryStorageClass)
		vrc.Spec.ProtectedPathName = ppath.Name
		vrc.Spec.ReplicationPath = ppath.SourceDir
		vrc.Spec.ProtectionPolicyNames, err = protectionPolicyNamesForVRC(
			vvr.Name, vvr.Spec.PrimaryStorageClass, vvr.Spec.ProtectionTopology, sourceSCName)
		if err != nil {
			return fmt.Errorf("VR %s/%s: %w", ns, name, err)
		}
		if err := controllerutil.SetOwnerReference(vr, vrc, k8s.Client().Scheme()); err != nil {
			return fmt.Errorf("failed to set owner reference on VRC %s: %w", vrc.Name, err)
		}
		if err := k8s.CreateVastReplicationContent(ctx, vrc); err != nil {
			return fmt.Errorf("failed to create VRC for VR %s/%s: %w", ns, name, err)
		}
		emit.Normalf(events.ReasonVRCCreated, "created VastReplicationContent %s/%s (pvcs=%s)",
			vrc.Namespace, vrc.Name, vrc.Spec.PVCs.String())
		bo.Reset()
		return nil
	}

	if existing.DeletionTimestamp != nil {
		return fmt.Errorf("%w: %s/%s", k8sclient.ErrVastReplicationContentTerminating, ns, name)
	}

	// VRC exists — apply any pending changes.
	if syncVRCReplicationState(existing, newState, emit) || syncVRCPVCs(existing, pvcs, emit) {
		if err := k8s.PatchVastReplicationContentSpec(ctx, existing); err != nil {
			return fmt.Errorf("failed to patch VRC for VR %s/%s: %w", ns, name, err)
		}
	}
	bo.Reset()
	return nil
}

// reconcileVGR ensures a Self VastReplicationContent exists for the given
// VolumeGroupReplication (which must be owned by a VastStorageClassReplication).
func (r *ReplicationObjectReconciler) reconcileVGR(ctx context.Context, name, ns string, bo *backoff.BoundBackoff) error {
	log := r.LogFor("vgr", ns+"/"+name)
	k8s := r.K8sFor(log)

	vgr, err := k8s.GetVolumeGroupReplication(ctx, name, ns)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return nil
		}
		return err
	}

	log.Info("=== reconciling VolumeGroupReplication ===")
	emit := r.EmitFor(ctx, log, vgr)

	if vgr.GetDeletionTimestamp() != nil {
		vrc, err := k8s.GetVastReplicationContent(ctx, name, ns)
		if err != nil && !k8serrors.IsNotFound(err) {
			return fmt.Errorf("get VRC for terminating VGR %s/%s: %w", ns, name, err)
		}
		if err == nil && vrc.GetDeletionTimestamp() == nil {
			log.Info("VolumeGroupReplication is being deleted, deleting associated VastReplicationContent",
				zap.String("vrc", vrc.Name))
			if err := k8s.DeleteVastReplicationContent(ctx, vrc); err != nil {
				return fmt.Errorf("delete VRC for terminating VGR %s/%s: %w", ns, name, err)
			}
		}
		return nil
	}

	// The owning VSCR tells us the StorageClass even before any PVCs exist.
	ownerVSCR := common.OwnerByKind(vgr.OwnerReferences, "VastStorageClassReplication")
	if ownerVSCR == nil {
		return fmt.Errorf("VolumeGroupReplication %s/%s has no VastStorageClassReplication owner reference", ns, name)
	}
	vscr, err := k8s.GetVastStorageClassReplication(ctx, ownerVSCR.Name, ns)
	if err != nil {
		return fmt.Errorf("failed to get VastStorageClassReplication %s/%s: %w", ns, ownerVSCR.Name, err)
	}

	// StorageClass is taken from the source-selector label stamped at VGR creation time.
	// Fetching the first PVC just to read the SC is unnecessary and fails on secondary
	// VGRs before mirrors exist.
	var sourceSCName string
	if vgr.Spec.Source.Selector != nil {
		sourceSCName = vgr.Spec.Source.Selector.MatchLabels[common.LabelStorageClass]
	}
	if sourceSCName == "" {
		return fmt.Errorf(
			"VolumeGroupReplication %s/%s is missing required label selector %q", ns, name, common.LabelStorageClass)
	}

	// Build the PVC list from the VGR status (empty on secondary before mirrors exist).
	pvcs := make(vastv1alpha1.PVCList, 0, len(vgr.Status.PersistentVolumeClaimsRefList))
	for _, ref := range vgr.Status.PersistentVolumeClaimsRefList {
		pvcs = append(pvcs, ref.Name)
	}
	sort.Strings(pvcs)
	if len(pvcs) == 0 {
		log.Info("VolumeGroupReplication has no PVCs yet.", zap.String("storageClass", sourceSCName))
	}

	newState := currentStateStr(vgr.Status.State)
	sourceSC, err := k8s.GetStorageClass(ctx, sourceSCName)
	if err != nil {
		return fmt.Errorf("failed to get StorageClass %s: %w", sourceSCName, err)
	}

	provType := vastv1alpha1.ProvisionerTypeFile
	if k8sclient.IsBlockStorageClass(sourceSC) {
		provType = vastv1alpha1.ProvisionerTypeBlock
	}
	vrcLabels := map[string]string{
		common.LabelManagedBy:  common.LabelManagedByValue,
		common.LabelSourceVSCR: ownerVSCR.Name,
	}

	existing, err := k8s.GetVastReplicationContent(ctx, name, ns)
	if err != nil {
		if !k8serrors.IsNotFound(err) {
			return fmt.Errorf("failed to get VRC for VGR %s/%s: %w", ns, name, err)
		}
		// First time: all immutable fields (including ppath) must be set at creation.
		ppath, err := resolveSourcePPath(ctx, k8s, sourceSC, r.Config.SSLVerify, log, vscr.Status.PpathName)
		if err != nil {
			if retryErr := handlePPathNetworkError(err, bo); retryErr != nil {
				return retryErr
			}
			return fmt.Errorf("VGR %s/%s: %w", ns, name, err)
		}
		vrc := r.buildContent(sourceSCName, vastv1alpha1.DestinationKindVolumeGroupReplication, name, ns, pvcs, vrcLabels)
		vrc.Spec.SyncPVCPV = vscr.Spec.SyncPVCPV
		vrc.Spec.ProvisionerType = provType
		vrc.Spec.ReplicationState = initialStateFromPrimary(newState, sourceSCName, vscr.Spec.PrimaryStorageClass)
		vrc.Spec.ProtectedPathName = ppath.Name
		vrc.Spec.ReplicationPath = ppath.SourceDir
		vrc.Spec.ProtectionPolicyNames, err = protectionPolicyNamesForVRC(
			vscr.Name, vscr.Spec.PrimaryStorageClass, vscr.Spec.ProtectionTopology, sourceSCName)
		if err != nil {
			return fmt.Errorf("VGR %s/%s: %w", ns, name, err)
		}
		if err := controllerutil.SetOwnerReference(vgr, vrc, k8s.Client().Scheme()); err != nil {
			return fmt.Errorf("failed to set owner reference on VRC %s: %w", vrc.Name, err)
		}
		if err := k8s.CreateVastReplicationContent(ctx, vrc); err != nil {
			return fmt.Errorf("failed to create VRC for VGR %s/%s: %w", ns, name, err)
		}
		emit.Normalf(events.ReasonVRCCreated, "created VastReplicationContent %s/%s (pvcs=%s)",
			vrc.Namespace, vrc.Name, vrc.Spec.PVCs.String())
		bo.Reset()
		return nil
	}

	if existing.DeletionTimestamp != nil {
		return fmt.Errorf("%w: %s/%s", k8sclient.ErrVastReplicationContentTerminating, ns, name)
	}

	// VRC exists — apply any pending changes in one patch.
	pvcChanged := syncVRCPVCs(existing, pvcs, emit)
	if syncVRCReplicationState(existing, newState, emit) || pvcChanged {
		if err := k8s.PatchVastReplicationContentSpec(ctx, existing); err != nil {
			return fmt.Errorf("failed to patch VRC for VGR %s/%s: %w", ns, name, err)
		}
	}

	// When the primary VGR gains new PVCs, the secondary VRCs must be
	// triggered immediately so they create mirror PVCs for the new primaries.
	if pvcChanged && sourceSCName == vscr.Spec.PrimaryStorageClass {
		touched, err := k8s.TouchSecondaryVRCs(ctx, vscr)
		for _, vrcName := range touched {
			log.Info("touched secondary VRC to trigger mirror PVC creation",
				zap.String("vrc", ns+"/"+vrcName))
		}
		if err != nil {
			return fmt.Errorf("touch secondary VRCs after primary PVC list change on VGR %s/%s: %w", ns, name, err)
		}
	}

	bo.Reset()
	return nil
}

// ---------------------------------------------------------------------------
// Helpers shared by reconcileVR and reconcileVGR
// ---------------------------------------------------------------------------

// syncVRCPVCs updates vrc.Spec.PVCs to pvcs when the lists differ, emits a
// Normal event and returns true.  Returns false without side-effects when the
// list is already up-to-date.
func syncVRCPVCs(vrc *vastv1alpha1.VastReplicationContent, pvcs vastv1alpha1.PVCList, emit *events.BoundReporter) bool {
	if pvcs.Equal(vrc.Spec.PVCs) {
		return false
	}
	vrc.Spec.PVCs = pvcs
	emit.Normalf(events.ReasonVRCUpdated, "VastReplicationContent %s/%s pvcs updated: %s",
		vrc.Namespace, vrc.Name, pvcs.String())
	return true
}

// syncVRCReplicationState updates vrc.Spec.ReplicationState to state when the
// value differs (no-ops when state is ""), emits a Normal event and returns
// true.  Returns false without side-effects when the state is already current.
func syncVRCReplicationState(vrc *vastv1alpha1.VastReplicationContent, state string, emit *events.BoundReporter) bool {
	if state == "" || vrc.Spec.ReplicationState == state {
		return false
	}
	old := vrc.Spec.ReplicationState
	vrc.Spec.ReplicationState = state
	emit.Normalf(events.ReasonVRCUpdated, "VastReplicationContent %s/%s replicationState %s → %s",
		vrc.Namespace, vrc.Name, old, state)
	return true
}

// currentStateStr converts a VolumeReplication/VolumeGroupReplication Status.State
// to the lowercase string stored in VastReplicationContent.Spec.ReplicationState.
// Returns "" when the state is Unknown so callers can skip propagation.
func currentStateStr(state replicationv1alpha1.State) string {
	if state == replicationv1alpha1.UnknownState {
		return ""
	}
	return strings.ToLower(string(state))
}

// initialStateFromPrimary returns current when it is non-empty.  Otherwise it
// derives the replication state from PrimaryStorageClass so that a VRC is born
// with the correct state even before csi-addons has populated the parent
// VolumeReplication/VolumeGroupReplication Status.
func initialStateFromPrimary(current, sourceSCName, primarySCName string) string {
	if current != "" {
		return current
	}
	if sourceSCName == primarySCName {
		return "primary"
	}
	return "secondary"
}

// resolveSourcePPath fetches the VAST protected path by its exact name,
// using a REST client built from sourceSC.
//
// Callers should check common.IsNetworkError on the returned error: when the
// source cluster is unreachable the VRC cannot be created yet, but this is a
// transient condition that does not merit a hard reconcile failure.
func resolveSourcePPath(
	ctx context.Context,
	k8sClient *k8sclient.K8sClient,
	sourceSC *storagev1.StorageClass,
	sslVerify bool,
	log *zap.Logger,
	ppathName string,
) (*typed.ProtectedPathDetailsModel, error) {
	rest, err := vmsrest.NewFromStorageClass(ctx, k8sClient, sourceSC, sslVerify, log)
	if err != nil {
		return nil, fmt.Errorf("failed to build VAST REST client from StorageClass %s: %w", sourceSC.Name, err)
	}
	ppath, err := rest.ProtectedPaths.Get(&typed.ProtectedPathSearchParams{
		Name:    expr.S(ppathName),
		RawData: vast_client.Params{"fields": "id,name,enabled,state,failure_reason,role,tenant_id,source_dir,protection_policy_name"},
	})
	if err != nil {
		if vast_client.IsNotFoundErr(err) {
			return nil, cerrors.NewRetryAfterError(err, time.Minute)
		}
		return nil, fmt.Errorf("failed to query protected path %q on StorageClass %s: %w",
			ppathName, sourceSC.Name, err)
	}
	return ppath, nil
}

// protectionPolicyNamesForVRC returns every protection policy whose snapshots
// may exist on scName's cluster.  Derived once at VRC creation from the parent
// replication topology so cleanup can use spec alone.
func protectionPolicyNamesForVRC(
	ownerName string,
	primarySC string,
	topology []vastv1alpha1.ReplicationTarget,
	scName string,
) ([]string, error) {
	names := vmsrest.ProtectionPolicyNamesByStorageClass(ownerName, primarySC, topology)[scName]
	if len(names) == 0 {
		return nil, fmt.Errorf(
			"no protection policies for StorageClass %q in topology of %q (primary %q)",
			scName, ownerName, primarySC)
	}
	return names, nil
}

// handlePPathNetworkError returns a Retryable error with an exponential backoff
// delay when err is a network error (unreachable cluster).  Returns nil when
// err is not a network error so the caller can propagate it as a hard failure.
func handlePPathNetworkError(err error, bo *backoff.BoundBackoff) error {
	if !common.IsNetworkError(err) {
		return nil
	}
	return cerrors.NewRetryAfterError(err, bo.Next())
}

// buildContent constructs a VastReplicationContent for the given VGR/VR.
func (r *ReplicationObjectReconciler) buildContent(
	scName string,
	kind, mirroredName, mirroredNamespace string,
	pvcs vastv1alpha1.PVCList,
	labels map[string]string,
) *vastv1alpha1.VastReplicationContent {
	return &vastv1alpha1.VastReplicationContent{
		TypeMeta: metav1.TypeMeta{
			APIVersion: vastv1alpha1.GroupVersion.String(),
			Kind:       "VastReplicationContent",
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:      mirroredName,
			Namespace: mirroredNamespace,
			Labels:    labels,
			// Finalizer injected at creation time so the object cannot be deleted
			// before VastReplicationContentReconciler has cleaned up all resources.
			Finalizers: []string{common.FinalizerReplicationContent},
		},
		Spec: vastv1alpha1.VastReplicationContentSpec{
			StorageClass: scName,
			Kind:         kind,
			PVCs:         pvcs,
		},
	}
}

// SetupReplicationObjectProvisionerController registers the combined
// VolumeReplication + VolumeGroupReplication controller with the manager.
func SetupReplicationObjectProvisionerController(
	mgr ctrl.Manager,
	k8sClient *k8sclient.K8sClient,
	logger *zap.Logger,
	cfg *config.Config,
) error {
	base, err := NewBaseReconciler(mgr, k8sClient, logger, cfg, "replicationobject")
	if err != nil {
		return err
	}
	r := &ReplicationObjectReconciler{BaseReconciler: base}

	return ctrl.NewControllerManagedBy(mgr).
		WithOptions(controllerOptions(cfg)).
		Named("replication").
		Watches(
			&replicationv1alpha1.VolumeReplication{},
			handler.EnqueueRequestsFromMapFunc(func(_ context.Context, obj client.Object) []reconcile.Request {
				return []reconcile.Request{{
					NamespacedName: types.NamespacedName{
						Name:      vrPrefix + obj.GetName(),
						Namespace: obj.GetNamespace(),
					},
				}}
			}),
			builder.WithPredicates(volumeReplicationPredicate()),
		).
		Watches(
			&replicationv1alpha1.VolumeGroupReplication{},
			handler.EnqueueRequestsFromMapFunc(func(_ context.Context, obj client.Object) []reconcile.Request {
				return []reconcile.Request{{
					NamespacedName: types.NamespacedName{
						Name:      vgrPrefix + obj.GetName(),
						Namespace: obj.GetNamespace(),
					},
				}}
			}),
			builder.WithPredicates(volumeGroupReplicationPredicate()),
		).
		Complete(r)
}
