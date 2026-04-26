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
	"strings"
	"time"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/core"
	"github.com/vast-data/go-vast-client/resources/typed"
	"go.uber.org/zap"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/backoff"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/ppathdir"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
	"github.com/vast-data/vast-csi/extensions-controller/internal/provisioner"
	vbuilder "github.com/vast-data/vast-csi/extensions-controller/internal/provisioner/builder"
)

// VastVolumeReplicationReconciler watches VastVolumeReplication objects and
// ensures one VolumeReplication exists per listed StorageClass, all pointing
// to the single PVC named in spec.volumeName.
type VastVolumeReplicationReconciler struct {
	BaseReconciler
}

// +kubebuilder:rbac:groups=vastdata.com,resources=vastvolumereplications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=vastdata.com,resources=vastvolumereplications/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=vastdata.com,resources=vastvolumereplications/finalizers,verbs=update
// +kubebuilder:rbac:groups=replication.storage.openshift.io,resources=volumereplications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=replication.storage.openshift.io,resources=volumereplicationclasses,verbs=get;list;watch;create
// +kubebuilder:rbac:groups=storage.k8s.io,resources=storageclasses,verbs=get;list;watch

func (r *VastVolumeReplicationReconciler) Reconcile(ctx context.Context, req ctrl.Request) (result ctrl.Result, retErr error) {
	defer r.Locker.Lock("vvr", req.Namespace, req.Name)()

	vvr, err := r.K8sClient.GetVastVolumeReplication(ctx, req.Name, req.Namespace)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	log := r.LogFor("vvr", req.NamespacedName.String())
	k8s := r.K8sFor(log)
	emit := r.EmitFor(ctx, log, vvr)
	bo := r.BackoffFor(req.NamespacedName)

	defer func() {
		if result.RequeueAfter == 0 {
			r.reconcileSyncStatus(ctx, k8s, vvr, retErr)
		}
	}()

	log.Info("=== reconciling VastVolumeReplication ===",
		zap.String("volumeName", vvr.Spec.VolumeName),
		zap.String("primaryStorageClass", vvr.Spec.PrimaryStorageClass),
		zap.Int("storageClasses", len(vvr.Spec.AllStorageClasses())))

	if vvr.GetDeletionTimestamp() != nil {
		return r.handleDeletion(ctx, log, emit, vvr, bo)
	}

	// Build one VMS REST client and fetch the StorageClass object per StorageClass name.
	restByStorageClass, err := vmsrest.RestFromStorageClasses(ctx, k8s, vvr.Spec.AllStorageClasses(), r.Config.SSLVerify, log)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to build VMS REST clients: %w", err)
	}
	scByStorageClass, err := k8sclient.ScsFromStorageClasses(ctx, k8s, vvr.Spec.AllStorageClasses())
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to fetch StorageClass objects: %w", err)
	}

	ensured, err := k8s.EnsureFinalizer(ctx, vvr, common.FinalizerVVR)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to add finalizer: %w", err)
	}
	if ensured {
		if err := r.validateOnce(k8s, vvr); err != nil {
			_ = k8s.RemoveFinalizer(ctx, vvr, common.FinalizerVVR)
			return ctrl.Result{}, err
		}
	}

	primaryChanged := r.ensurePrimaryStorageClass(vvr, emit)

	if r.Config.ApplyExistingPVCs && primaryChanged {
		scName := vvr.Spec.PrimaryStorageClass
		if err := k8s.ApplyExistingPVCs(ctx, scName, scByStorageClass[scName], restByStorageClass[scName], log); err != nil {
			log.Warn("PVC label backfill failed; continuing reconcile",
				zap.String("sc", scName), zap.Error(err))
		}
	}

	if r.ensureStorageClassPreview(vvr) || primaryChanged || r.ensureLastFailoverType(vvr, emit) {
		if err := k8s.UpdateVastVolumeReplicationStatus(ctx, vvr); err != nil {
			return ctrl.Result{}, err
		}
	}

	if vvr.Spec.Resync {
		if err := r.ensureResync(ctx, k8s, emit, vvr); err != nil {
			return ctrl.Result{}, err
		}
		// Return after triggering resync so that ensureVR in this cycle does not
		// immediately revert the replicationState back to Primary.
		return ctrl.Result{}, nil
	}

	// PpathDir is immutable once set: predict it only on the first reconcile.
	primaryPpathDir := vvr.Status.PpathDir
	if primaryPpathDir == "" {
		primarySC, err := k8s.GetStorageClass(ctx, vvr.Spec.PrimaryStorageClass)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to get primary StorageClass %s: %w",
				vvr.Spec.PrimaryStorageClass, err)
		}
		primaryPpathDir, err = ppathdir.Predict(ctx, k8s, primarySC, r.Config.SSLVerify, log, vvr.Spec.VolumeName, vvr.Namespace)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to compute PpathDir for StorageClass %s: %w",
				vvr.Spec.PrimaryStorageClass, err)
		}
		vvr.Status.PpathDir = primaryPpathDir
		if err := k8s.UpdateVastVolumeReplicationStatus(ctx, vvr); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Resolve any empty PeerName fields via live peer discovery.
	needsUpdate := false
	for i := range vvr.Spec.ProtectionTopology {
		t := &vvr.Spec.ProtectionTopology[i]
		if t.PeerName == "" {
			if err := vmsrest.ResolvePeerName(t, restByStorageClass[t.Source], restByStorageClass[t.Destination]); err != nil {
				return ctrl.Result{}, fmt.Errorf("protectionTopology[%d]: %w", i, err)
			}
			needsUpdate = true
		}
	}
	if needsUpdate {
		if err := k8s.UpdateVastVolumeReplication(ctx, vvr); err != nil {
			return ctrl.Result{}, err
		}
		// The spec update will re-trigger reconciliation with all PeerNames set.
		return ctrl.Result{}, nil
	}

	// ppath is already established — just verify it is still active.
	// Skips DiscoverLinkPolicies on every steady-state reconcile.
	ppathName := vvr.Status.PpathName
	if ppathName != "" {
		// ppath is already established — just verify it is still active.
		if err := vmsrest.IsPpathActive(restByStorageClass[vvr.Spec.PrimaryStorageClass], ppathName); err != nil {
			if vast_client.IsNotFoundErr(err) {
				// ppath was deleted externally — reset status and recreate via slow path below.
				log.Info("ppath no longer exists, will recreate", zap.String("ppath", ppathName))
				ppathName = ""
				vvr.Status.PpathName = ""
				if err := k8s.UpdateVastVolumeReplicationStatus(ctx, vvr); err != nil {
					return ctrl.Result{}, err
				}
			} else {
				emit.Warning(events.ReasonPpathNotReady, err.Error())
				return r.maybeBackoffRetry(bo, err, log)
			}
		}
	}
	if ppathName == "" {
		// ppath not yet created (or was reset) — discover policies and build full topology.
		edges := vmsrest.NewReplicationEdgesList(vvr.Spec.ProtectionTopology, vvr.Spec.PrimaryStorageClass)
		tmpl := vmsrest.SpecTemplateToParams(vvr.Name, vvr.Spec.ProtectionPolicyTemplate)
		policyPairs, err := vmsrest.DiscoverLinkPolicies(restByStorageClass, scByStorageClass, edges, tmpl, log)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to ensure protection policies: %w", err)
		}

		ppathName, err = vmsrest.EnsureConstellationPpath(
			restByStorageClass, policyPairs, vvr.Spec.PrimaryStorageClass, vvr.Name, primaryPpathDir, log,
		)
		if err != nil {
			emit.Warning(events.ReasonPpathNotReady, err.Error())
			return r.maybeBackoffRetry(bo, err, log)
		}

		vvr.Status.PpathName = ppathName
		if err := k8s.UpdateVastVolumeReplicationStatus(ctx, vvr); err != nil {
			return ctrl.Result{}, err
		}
	}

	var errs cerrors.DeferredError
	// Use primary-first ordering so the primary VRC exists in the constellation
	// before any secondary VRC reconciles for the first time.
	allSCs := vvr.Spec.AllStorageClassesPrimaryFirst()
	for i, scName := range allSCs {
		vrName, created, err := r.ensureVR(ctx, emit, vvr, scName, ppathName, primaryChanged)
		if err != nil {
			errs.Add(fmt.Errorf("SC %s: %w", scName, err))
		}
		// When a VR is freshly created, wait until the ReplicationObjectReconciler
		// has created the corresponding VRC before moving on to the next SC.
		// Secondary VRCs must find the primary VRC already present in the
		// constellation when they first reconcile so classifyConstellationPVCs
		// can locate the source PVC and create the mirror PVC.
		if created && i < len(allSCs)-1 {
			if waitErr := k8s.WaitForVRC(ctx, vvr.Namespace, vrName, 30*time.Second); waitErr != nil {
				log.Warn(
					"proceeding without confirmed VRC",
					zap.String("vr", vrName),
					zap.Error(waitErr),
				)
			}
		}
	}

	if err := r.syncVRReplicationStates(ctx, k8s, emit, vvr); err != nil {
		errs.Add(err)
	}

	if errs.Err() == nil {
		bo.Reset()
	}
	return r.maybeBackoffRetry(bo, errs.Err(), log)
}

// reconcileSyncStatus derives the desired SyncStatus from the overall
// reconcile result and the VolumeReplication state, then persists it if it
// changed.  It swallows its own write errors so that the caller's original
// reconcile error is not masked.
func (r *VastVolumeReplicationReconciler) reconcileSyncStatus(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	vvr *vastv1alpha1.VastVolumeReplication,
	reconcileErr error,
) {
	var desired string

	switch {
	case vvr.GetDeletionTimestamp() != nil:
		desired = vastv1alpha1.SyncStatusDeleting
	case reconcileErr != nil && isNetworkError(reconcileErr):
		desired = vastv1alpha1.SyncStatusUnreachable
	case reconcileErr != nil && isValidationError(reconcileErr):
		desired = vastv1alpha1.SyncStatusInvalid
	case reconcileErr != nil:
		desired = vastv1alpha1.SyncStatusError
	default:
		vrName := vrNameForSC(vvr.Name, vvr.Spec.PrimaryStorageClass)
		vr, err := k8s.GetVolumeReplication(ctx, vrName, vvr.Namespace)
		if err != nil {
			return
		}
		if vr.Status.State == replicationv1alpha1.PrimaryState {
			desired = vastv1alpha1.SyncStatusCompleted
		} else {
			desired = vastv1alpha1.SyncStatusInProgress
		}
	}

	if vvr.Status.SyncStatus == desired {
		return
	}
	vvr.Status.SyncStatus = desired
	_ = k8s.UpdateVastVolumeReplicationStatus(ctx, vvr)
}

// validateOnce runs static spec validation exactly once — before the finalizer
// is added (i.e. on the very first reconcile).  Any failure returns a
// *provisioner.ValidationError, which sets SyncStatus=Invalid.
func (r *VastVolumeReplicationReconciler) validateOnce(_ *k8sclient.K8sClient, vvr *vastv1alpha1.VastVolumeReplication) error {
	if err := vvr.Spec.Validate(); err != nil {
		return cerrors.NewValidationError("%s", err.Error())
	}
	return nil
}

func (r *VastVolumeReplicationReconciler) handleDeletion(
	ctx context.Context,
	log *zap.Logger,
	emit *events.BoundReporter,
	vvr *vastv1alpha1.VastVolumeReplication,
	bo *backoff.BoundBackoff,
) (ctrl.Result, error) {
	k8s := r.K8sFor(log)

	if !k8s.HasFinalizer(vvr, common.FinalizerVVR) {
		return ctrl.Result{}, nil
	}

	for _, scName := range vvr.Spec.AllStorageClasses() {
		name := vrNameForSC(vvr.Name, scName)
		if err := k8s.DeleteVolumeReplication(ctx, name, vvr.Namespace); err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to delete VolumeReplication %s/%s: %w", vvr.Namespace, name, err)
		}
	}

	remainingVRs := r.countOwnedVRs(ctx, vvr)
	if remainingVRs > 0 {
		log.Info("waiting for owned VolumeReplications to be deleted",
			zap.Int("remaining", remainingVRs))
		emit.Normalf(events.ReasonCleanupStarted,
			"waiting for %d owned VolumeReplication(s) to be deleted before removing finalizer",
			remainingVRs)
		return ctrl.Result{RequeueAfter: bo.Next()}, nil
	}

	// Also wait for all VastReplicationContents labelled with this VVR to be
	// gone before removing our finalizer, for the same reason as the VSCR
	// controller: VRCs look up their parent VVR during cleanup, and removing
	// the finalizer too early would cause a "not found" error there.
	vrcs, err := k8s.ListVastReplicationContentsByLabelSelector(ctx, vvr.Namespace,
		map[string]string{common.LabelSourceVVR: vvr.Name})
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to list VastReplicationContents: %w", err)
	}
	if len(vrcs) > 0 {
		log.Info("waiting for owned VastReplicationContents to finish cleanup",
			zap.Int("remaining", len(vrcs)))
		emit.Normalf(events.ReasonCleanupStarted,
			"waiting for %d VastReplicationContent(s) to finish cleanup before removing finalizer",
			len(vrcs))
		return ctrl.Result{RequeueAfter: bo.Next()}, nil
	}

	bo.Reset()

	// Make sure the protected path is gone before the finalizer is removed.
	if vvr.Spec.PrimaryStorageClass != "" && vvr.Status.PpathName != "" {
		if rest, _, err := vmsrest.NewFromStorageClassName(ctx, k8s, vvr.Spec.PrimaryStorageClass, r.Config.SSLVerify, log); err == nil {
			ppath, _ := rest.ProtectedPaths.Get(&typed.ProtectedPathSearchParams{
				RawData: vast_client.Params{
					"name":   vvr.Status.PpathName,
					"fields": "id,name,enabled",
				},
			})
			if ppath != nil {
				if ppath.Enabled {
					rest.Untyped.ProtectedPaths.Update(ppath.Id, core.Params{"enabled": false})
				}
				if _, err := rest.ProtectedPaths.DeleteById(ppath.Id, 2*time.Minute); err != nil {
					log.With(zap.Error(err)).Info("failed to delete protected path for VastVolumeReplication")
				}
			}
		}
	}

	// Delete the protection policies that were created for this VVR.
	if vvr.Spec.PrimaryStorageClass != "" {
		vmsrest.DeleteProtectionPolicies(
			ctx, k8s,
			vvr.Name,
			vvr.Spec.PrimaryStorageClass,
			vvr.Spec.ProtectionTopology,
			r.Config.SSLVerify,
			log,
		)
	}

	if err := k8s.RemoveFinalizer(ctx, vvr, common.FinalizerVVR); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to remove finalizer: %w", err)
	}
	log.Info("all owned VolumeReplications and VastReplicationContents deleted, finalizer removed")
	return ctrl.Result{}, nil
}

func (r *VastVolumeReplicationReconciler) countOwnedVRs(
	ctx context.Context,
	vvr *vastv1alpha1.VastVolumeReplication,
) int {
	count := 0
	for _, scName := range vvr.Spec.AllStorageClasses() {
		name := vrNameForSC(vvr.Name, string(scName))
		if _, err := r.K8sClient.GetVolumeReplication(ctx, name, vvr.Namespace); err == nil {
			count++
		}
	}
	return count
}

// ensureVolumeReplicationClass creates (or no-ops) the VolumeReplicationClass
// for the given StorageClass.
//
// ppathName is the pre-created protected-path name on the primary site.
// It is non-empty only for the primary StorageClass; secondary classes receive "".
func (r *VastVolumeReplicationReconciler) ensureVolumeReplicationClass(
	ctx context.Context,
	emit *events.BoundReporter,
	vvr *vastv1alpha1.VastVolumeReplication,
	scName string,
	ppathName string,
) (className string, err error) {
	k8s := r.K8sFor(emit.Logger())

	sc, err := k8s.GetStorageClass(ctx, scName)
	if err != nil {
		return "", fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
	}

	className, err = provisioner.FormatReplicationClassName(ctx, k8s, provisioner.VVRReplicationClassFormat, sc)
	if err != nil {
		return "", fmt.Errorf("failed to format replication class name for SC %s: %w", scName, err)
	}

	csiParams := k8s.ExtractPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
	secretName := csiParams["provisioner-secret-name"]
	secretNamespace := csiParams["provisioner-secret-namespace"]
	if secretName == "" || secretNamespace == "" {
		return "", fmt.Errorf("StorageClass %s is missing provisioner-secret-name / provisioner-secret-namespace parameters", scName)
	}

	subsystem := sc.Parameters[common.StorageClassParameterSubsystem]

	vrcBuilder := vbuilder.NewVolumeReplicationClass(className, "").
		WithProvisioner(sc.Provisioner).
		WithParameter(common.CSIAddonsParamReplicationSecretName, secretName).
		WithParameter(common.CSIAddonsParamReplicationSecretNamespace, secretNamespace).
		WithParameter(common.ReplicationParamPpathName, ppathName).
		WithParameter(common.ReplicationParamStorageClass, scName).
		WithManagedByLabel()
	if subsystem != "" {
		vrcBuilder = vrcBuilder.WithParameter(common.ReplicationParamSubsystem, subsystem)
	}

	vrc := vrcBuilder.Result()
	vrcCreated, err := k8s.EnsureVolumeReplicationClass(ctx, vrc)
	if err != nil {
		return "", fmt.Errorf("failed to ensure VolumeReplicationClass %s: %w", className, err)
	}
	if vrcCreated {
		emit.Normalf(events.ReasonReplicationClassEnsured,
			"created VolumeReplicationClass %s for StorageClass %q", className, scName)
	}

	return className, nil
}

// syncVRReplicationStates resolves split-brain situations where multiple
// VolumeReplications are simultaneously confirmed primary by csi-addons
// (Spec.ReplicationState == Primary AND Status.State == Primary).
//
// For each such candidate it queries the VAST cluster via REST to read the
// protected-path role.  The candidate whose ppath role is "source" is the true
// primary; all other confirmed-primary candidates are demoted to Secondary.
//
// If zero or one candidate exists, or if no candidate reports role "source"
// yet (VAST failover still in progress), the function is a no-op.
func (r *VastVolumeReplicationReconciler) syncVRReplicationStates(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
	vvr *vastv1alpha1.VastVolumeReplication,
) error {
	// Collect every VR that csi-addons considers primary.
	var candidates []string
	for _, scName := range vvr.Spec.AllStorageClasses() {
		vr, err := k8s.GetVolumeReplication(ctx, vrNameForSC(vvr.Name, scName), vvr.Namespace)
		if err != nil {
			if k8serrors.IsNotFound(err) {
				// VR not yet created (ensureVR may have failed earlier); skip.
				continue
			}
			return fmt.Errorf("failed to get VolumeReplication for SC %s: %w", scName, err)
		}
		if k8sclient.IsVRConfirmedPrimary(vr) {
			candidates = append(candidates, scName)
		}
	}
	if len(candidates) <= 1 {
		return nil
	}

	// Multiple confirmed-primary VRs — query each VAST cluster individually
	// to find the true source.
	var truePrimarySC string
	for _, scName := range candidates {
		rest, _, err := vmsrest.NewFromStorageClassName(ctx, k8s, scName, r.Config.SSLVerify, emit.Logger())
		if err != nil {
			return fmt.Errorf("failed to build REST client for SC %s: %w", scName, err)
		}
		ppath, err := vmsrest.GetPpath(rest, vvr.Status.PpathName)
		if err != nil {
			return fmt.Errorf("failed to get ppath %q for SC %s: %w", vvr.Status.PpathName, scName, err)
		}
		if strings.ToLower(ppath.Role) == "source" {
			truePrimarySC = scName
			break
		}
	}
	if truePrimarySC == "" {
		// VAST failover not yet complete — nothing to demote.
		return nil
	}

	var errs cerrors.DeferredError
	for _, scName := range candidates {
		if scName == truePrimarySC {
			continue
		}
		if err := r.ensureReplicationState(ctx, k8s, emit, vvr.Namespace, vrNameForSC(vvr.Name, scName), scName, replicationv1alpha1.Secondary, false); err != nil {
			errs.Add(fmt.Errorf("SC %s: %w", scName, err))
		}
	}
	return errs.Err()
}

// ensureVR creates or updates the VolumeReplication for the given StorageClass.
// Returns (true, nil) when the VR was freshly created, (false, nil) when it
// already existed, and (false, err) on error.
// primaryChanged must be true when the primary StorageClass switched this reconcile
// cycle so that an in-progress resync can be overridden with the failover state.
func (r *VastVolumeReplicationReconciler) ensureVR(
	ctx context.Context,
	emit *events.BoundReporter,
	vvr *vastv1alpha1.VastVolumeReplication,
	scName string,
	ppathName string,
	primaryChanged bool,
) (vrName string, created bool, err error) {
	k8s := r.K8sFor(emit.Logger())

	className, err := r.ensureVolumeReplicationClass(ctx, emit, vvr, scName, ppathName)
	if err != nil {
		return "", false, err
	}

	vrName = vrNameForSC(vvr.Name, scName)

	isPrimary := scName == vvr.Spec.PrimaryStorageClass
	state := replicationv1alpha1.Secondary
	if isPrimary {
		state = replicationv1alpha1.Primary
	}

	// Determine the PVC name the VolumeReplication should point at:
	//   - Primary SC  → the original source PVC (vvr.Spec.VolumeName).
	//   - Secondary SC → the mirror PVC that VastReplicationContent created on
	//     this cluster.  Its name is derived the same way as during PVC creation
	//     so that csi-addons replicates the correct volume.
	dataSourcePVC := vvr.Spec.VolumeName
	if !isPrimary {
		mirrorPVCName, err := r.mirrorPVCName(ctx, k8s, vvr, scName)
		if err != nil {
			return "", false, fmt.Errorf("failed to compute mirror PVC name for SC %s: %w", scName, err)
		}
		dataSourcePVC = mirrorPVCName
	}

	vr, err := vbuilder.NewVolumeReplication(vrName, vvr.Namespace).
		WithManagedByLabel().
		WithLabelsMap(map[string]string{common.LabelStorageClass: scName}).
		WithVolumeReplicationClass(className).
		WithReplicationState(state).
		WithDataSource(dataSourcePVC).
		WithAutoResync(true).
		WithOwnerRef(vvr, k8s.Client().Scheme()).
		Build()
	if err != nil {
		return "", false, err
	}

	wasCreated, err := k8s.EnsureVolumeReplication(ctx, vr)
	if err != nil {
		return "", false, fmt.Errorf("failed to ensure VolumeReplication %s/%s: %w", vvr.Namespace, vrName, err)
	}
	if wasCreated {
		emit.Normalf(events.ReasonVolumeReplicationCreated,
			"created VolumeReplication %s/%s for StorageClass %q (replicationState=%s, dataSource=%s)",
			vvr.Namespace, vrName, scName, state, dataSourcePVC)
		return vrName, true, nil
	}

	// Only drive the replicationState of the primary storage class.  Secondary
	// VRs reflect the actual VAST ppath role via csi-addons Status.State, which
	// the VR controller propagates into VastReplicationContent.
	if !isPrimary {
		return vrName, false, nil
	}
	return vrName, false, r.ensureReplicationState(ctx, k8s, emit, vvr.Namespace, vrName, scName, state, primaryChanged)
}

// mirrorPVCName computes the expected name of the mirror PVC on a secondary
// StorageClass cluster using the same FormatPVCName logic used by
// VastReplicationContent when it creates mirror PVCs.
func (r *VastVolumeReplicationReconciler) mirrorPVCName(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	vvr *vastv1alpha1.VastVolumeReplication,
	destSCName string,
) (string, error) {
	sourcePVC, sourcePV, bound, err := k8s.GetPVCandPV(ctx, vvr.Spec.VolumeName, vvr.Namespace)
	if err != nil {
		return "", fmt.Errorf("failed to get source PVC/PV %s/%s: %w", vvr.Namespace, vvr.Spec.VolumeName, err)
	}
	if !bound {
		return "", cerrors.NewRetryAfterError(
			fmt.Errorf("PVC %s/%s not yet bound", vvr.Namespace, vvr.Spec.VolumeName),
			15*time.Second,
		)
	}

	destSC, err := k8s.GetStorageClass(ctx, destSCName)
	if err != nil {
		return "", fmt.Errorf("failed to get destination StorageClass %s: %w", destSCName, err)
	}

	return provisioner.FormatPVCName(ctx, k8s, r.Config.PVCNameFormat, sourcePVC, sourcePV, destSC)
}

// ensureReplicationState syncs the replicationState of an existing VolumeReplication
// to the desired state (e.g. after a primary StorageClass switch).
// primaryChanged must be true when the primary StorageClass switched this reconcile
// cycle so that an in-progress resync can be overridden with the failover state.
func (r *VastVolumeReplicationReconciler) ensureReplicationState(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
	namespace, vrName, scName string,
	desired replicationv1alpha1.ReplicationState,
	primaryChanged bool,
) error {
	existing, err := k8s.GetVolumeReplication(ctx, vrName, namespace)
	if err != nil {
		return fmt.Errorf("failed to get VolumeReplication %s/%s: %w", namespace, vrName, err)
	}
	if existing.Spec.ReplicationState == desired {
		return nil
	}
	// When promoting to Primary, don't override an in-progress resync unless a
	// real failover (primaryStorageClass change) was detected in this reconcile cycle.
	// Demotions to Secondary always proceed regardless.
	if desired == replicationv1alpha1.Primary &&
		existing.Spec.ReplicationState == replicationv1alpha1.Resync &&
		!primaryChanged {
		return nil
	}
	if err := k8s.PatchVolumeReplicationState(ctx, existing, desired); err != nil {
		return fmt.Errorf("failed to patch replicationState on VolumeReplication %s/%s: %w",
			namespace, vrName, err)
	}
	emit.Normalf(events.ReasonVolumeReplicationUpdated,
		"updated VolumeReplication %s/%s replicationState → %s (StorageClass %q)",
		namespace, vrName, desired, scName)
	return nil
}

// vrNameForSC returns the deterministic VolumeReplication name for a VVR + StorageClass pair.
func vrNameForSC(vvrName, scName string) string {
	safe := strings.ReplaceAll(scName, ".", "-")
	return fmt.Sprintf("%s-%s", vvrName, safe)
}

func (r *VastVolumeReplicationReconciler) ensureStorageClassPreview(vvr *vastv1alpha1.VastVolumeReplication) bool {
	preview := vastv1alpha1.DisplayableList(vvr.Spec.AllStorageClasses()).String()
	if vvr.Status.StorageClassesPreview == preview {
		return false
	}
	vvr.Status.StorageClassesPreview = preview
	return true
}

func (r *VastVolumeReplicationReconciler) ensurePrimaryStorageClass(vvr *vastv1alpha1.VastVolumeReplication, emit *events.BoundReporter) bool {
	if vvr.Status.CurrentPrimaryStorageClass == vvr.Spec.PrimaryStorageClass {
		return false
	}
	old := vvr.Status.CurrentPrimaryStorageClass
	vvr.Status.CurrentPrimaryStorageClass = vvr.Spec.PrimaryStorageClass
	if old == "" {
		emit.Normalf("PrimaryStorageClassSet",
			"primary StorageClass set to %q", vvr.Spec.PrimaryStorageClass)
	} else {
		emit.Normalf("PrimaryStorageClassChanged",
			"primary StorageClass switched from %q to %q", old, vvr.Spec.PrimaryStorageClass)
	}
	return true
}

func (r *VastVolumeReplicationReconciler) ensureLastFailoverType(vvr *vastv1alpha1.VastVolumeReplication, emit *events.BoundReporter) bool {
	if vvr.Status.LastFailoverType == vvr.Spec.FailoverType {
		return false
	}
	old := vvr.Status.LastFailoverType
	vvr.Status.LastFailoverType = vvr.Spec.FailoverType
	if vvr.Spec.FailoverType != "" {
		if old == "" {
			emit.Normalf("FailoverTypeSet",
				"failoverType set to %q", vvr.Spec.FailoverType)
		} else {
			emit.Normalf("FailoverTypeChanged",
				"failoverType changed from %q to %q", old, vvr.Spec.FailoverType)
		}
	}
	return true
}

// ensureResync sets replicationState=resync on the primary VolumeReplication
func (r *VastVolumeReplicationReconciler) ensureResync(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
	vvr *vastv1alpha1.VastVolumeReplication,
) error {
	vrName := vrNameForSC(vvr.Name, vvr.Spec.PrimaryStorageClass)
	existing, err := k8s.GetVolumeReplication(ctx, vrName, vvr.Namespace)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			// VR not yet created — normal on first reconcile; clear the flag
			// so we don't loop.  The user can set Resync=true again once
			// provisioning has completed.
			emit.Logger().Info("resync skipped: VolumeReplication not yet created; clearing Resync flag",
				zap.String("vr", vrName))
			return k8s.PatchVVRResync(ctx, vvr)
		}
		return fmt.Errorf("ensureResync: failed to get VolumeReplication %s/%s: %w", vvr.Namespace, vrName, err)
	}
	if err := k8s.PatchVolumeReplicationState(ctx, existing, replicationv1alpha1.Resync); err != nil {
		return fmt.Errorf("ensureResync: failed to patch replicationState on VolumeReplication %s/%s: %w", vvr.Namespace, vrName, err)
	}
	emit.Normalf("ResyncTriggered",
		"replicationState set to resync on VolumeReplication %s/%s", vvr.Namespace, vrName)

	if err := k8s.PatchVVRResync(ctx, vvr); err != nil {
		return fmt.Errorf("ensureResync: failed to clear Resync flag on VVR %s/%s: %w", vvr.Namespace, vvr.Name, err)
	}
	return nil
}

// SetupVastVolumeReplicationController registers the reconciler with the manager.
func SetupVastVolumeReplicationController(
	mgr ctrl.Manager,
	k8sClient *k8sclient.K8sClient,
	logger *zap.Logger,
	cfg *config.Config,
) error {
	base, err := NewBaseReconciler(mgr, k8sClient, logger, cfg, "vastvolumereplication")
	if err != nil {
		return err
	}
	r := &VastVolumeReplicationReconciler{BaseReconciler: base}

	return ctrl.NewControllerManagedBy(mgr).
		For(&vastv1alpha1.VastVolumeReplication{}).
		Owns(&replicationv1alpha1.VolumeReplication{},
			builder.WithPredicates(ownedVRPredicate())).
		Named("vastvolumereplication").
		Complete(r)
}
