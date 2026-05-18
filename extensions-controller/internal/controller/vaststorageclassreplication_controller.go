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
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/backoff"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"go.uber.org/zap"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"

	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/ppathdir"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
	"github.com/vast-data/vast-csi/extensions-controller/internal/provisioner"
	vbuilder "github.com/vast-data/vast-csi/extensions-controller/internal/provisioner/builder"
)

// VastStorageClassReplicationReconciler watches VastStorageClassReplication objects
// and ensures one VolumeGroupReplication exists per listed StorageClass.
type VastStorageClassReplicationReconciler struct {
	BaseReconciler
}

// +kubebuilder:rbac:groups=vastdata.com,resources=vaststorageclassreplications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=vastdata.com,resources=vaststorageclassreplications/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=vastdata.com,resources=vaststorageclassreplications/finalizers,verbs=update
// +kubebuilder:rbac:groups=replication.storage.openshift.io,resources=volumegroupreplications,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=replication.storage.openshift.io,resources=volumereplicationclasses,verbs=get;list;watch;create
// +kubebuilder:rbac:groups=replication.storage.openshift.io,resources=volumegroupreplicationclasses,verbs=get;list;watch;create
// +kubebuilder:rbac:groups=storage.k8s.io,resources=storageclasses,verbs=get;list;watch

func (r *VastStorageClassReplicationReconciler) Reconcile(ctx context.Context, req ctrl.Request) (result ctrl.Result, retErr error) {
	defer r.Locker.Lock("vscr", req.Namespace, req.Name)()

	vscr, err := r.K8sClient.GetVastStorageClassReplication(ctx, req.Name, req.Namespace)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	log := r.LogFor("vscr", req.NamespacedName.String())
	k8s := r.K8sFor(log)
	emit := r.EmitFor(ctx, log, vscr)
	bo := r.BackoffFor(req.NamespacedName)

	defer func() {
		if result.RequeueAfter == 0 {
			r.reconcileSyncStatus(ctx, k8s, vscr, retErr)
		}
	}()

	log.Info("=== reconciling VastStorageClassReplication ===",
		zap.String("primaryStorageClass", vscr.Spec.PrimaryStorageClass),
		zap.Int("storageClasses", len(vscr.Spec.AllStorageClasses())))

	if vscr.GetDeletionTimestamp() != nil {
		return r.handleDeletion(ctx, log, emit, vscr, bo)
	}

	// Build one VMS REST client and fetch the StorageClass object per StorageClass name.
	restByStorageClass, err := vmsrest.RestFromStorageClasses(ctx, k8s, vscr.Spec.AllStorageClasses(), r.Config.SSLVerify, log)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to build VMS REST clients: %w", err)
	}
	scByStorageClass, err := k8sclient.ScsFromStorageClasses(ctx, k8s, vscr.Spec.AllStorageClasses())
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to fetch StorageClass objects: %w", err)
	}

	ensured, err := k8s.EnsureFinalizer(ctx, vscr, common.FinalizerVSCR)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to add finalizer: %w", err)
	}
	if ensured {
		if err := r.validateOnce(ctx, k8s, vscr, restByStorageClass); err != nil {
			_ = k8s.RemoveFinalizer(ctx, vscr, common.FinalizerVSCR)
			return ctrl.Result{}, err
		}
	}

	primaryChanged := r.ensurePrimaryStorageClass(vscr, emit)

	if r.Config.ApplyExistingPVCs && primaryChanged {
		log.Info("ensuring existing PVCs have necessary labels")
		scName := vscr.Spec.PrimaryStorageClass
		if err := k8s.ApplyExistingPVCs(ctx, scName, scByStorageClass[scName], restByStorageClass[scName], vscr.Spec.AllStorageClasses(), log); err != nil {
			log.Info("PVC label backfill failed; continuing reconcile",
				zap.String("sc", scName), zap.Error(err))
		}
	}

	if r.ensureStorageClassPreview(vscr) || primaryChanged || r.ensureLastFailoverType(vscr, emit) {
		if err := k8s.UpdateVastStorageClassReplicationStatus(ctx, vscr); err != nil {
			return ctrl.Result{}, err
		}
	}

	if vscr.Spec.Resync {
		if err := r.ensureResync(ctx, k8s, emit, vscr); err != nil {
			return ctrl.Result{}, err
		}
		// Return after triggering resync so that ensureVGR in this cycle does not
		// immediately revert the replicationState back to Primary.
		return ctrl.Result{}, nil
	}

	// Resolve any empty PeerName fields via live peer discovery.
	needsUpdate := false
	for i := range vscr.Spec.ProtectionTopology {
		t := &vscr.Spec.ProtectionTopology[i]
		if t.PeerName == "" {
			if err := vmsrest.ResolvePeerName(t, restByStorageClass[t.Source], restByStorageClass[t.Destination]); err != nil {
				return ctrl.Result{}, fmt.Errorf("protectionTopology[%d]: %w", i, err)
			}
			needsUpdate = true
		}
	}
	if needsUpdate {
		if err := k8s.UpdateVastStorageClassReplication(ctx, vscr); err != nil {
			return ctrl.Result{}, err
		}
		// The spec update will re-trigger reconciliation with all PeerNames set.
		return ctrl.Result{}, nil
	}

	// PpathDirMapping is immutable once populated: predict dirs only on the first reconcile.
	if len(vscr.Status.PpathDirMapping) == 0 {
		mapping := make(map[string]string, len(vscr.Spec.AllStorageClasses()))

		primarySC, err := k8s.GetStorageClass(ctx, vscr.Spec.PrimaryStorageClass)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to get primary StorageClass %s: %w", vscr.Spec.PrimaryStorageClass, err)
		}

		if ppathdir.IsSubsystemLevel(k8s, primarySC) {
			// Subsystem-level block replication: secondary clusters don't have a
			// subsystem yet — VAST creates it via replication and preserves the
			// source path.  Predict only from the primary and share the result
			// across all StorageClasses in the constellation.
			primaryDir, err := ppathdir.Predict(ctx, k8s, primarySC, r.Config.SSLVerify, log, "", "")
			if err != nil {
				return ctrl.Result{}, fmt.Errorf("failed to compute PpathDir for primary StorageClass %s: %w", vscr.Spec.PrimaryStorageClass, err)
			}
			for _, scName := range vscr.Spec.AllStorageClasses() {
				mapping[scName] = primaryDir
			}
		} else {
			for _, scName := range vscr.Spec.AllStorageClasses() {
				sc, err := k8s.GetStorageClass(ctx, scName)
				if err != nil {
					return ctrl.Result{}, fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
				}
				dir, err := ppathdir.Predict(ctx, k8s, sc, r.Config.SSLVerify, log, "", "")
				if err != nil {
					return ctrl.Result{}, fmt.Errorf("failed to compute PpathDir for StorageClass %s: %w", scName, err)
				}
				mapping[scName] = dir
			}
		}

		vscr.Status.PpathDirMapping = mapping
		if err := k8s.UpdateVastStorageClassReplicationStatus(ctx, vscr); err != nil {
			return ctrl.Result{}, err
		}
	}

	ppathName := vscr.Status.PpathName
	if ppathName != "" {
		// ppath is already established — just verify it is still active.
		if err := vmsrest.IsPpathActive(restByStorageClass[vscr.Spec.PrimaryStorageClass], ppathName); err != nil {
			if vast_client.IsNotFoundErr(err) {
				// ppath was deleted externally — reset status and recreate it.
				log.Info("ppath no longer exists, will recreate", zap.String("ppath", ppathName))
				ppathName = ""
				vscr.Status.PpathName = ""
				if err := k8s.UpdateVastStorageClassReplicationStatus(ctx, vscr); err != nil {
					return ctrl.Result{}, err
				}
			} else {
				emit.Warning(events.ReasonPpathNotReady, err.Error())
				return r.maybeBackoffRetry(bo, err, log)
			}
		}
	} else {
		//  ppath not yet created — discover policies and build full topology.
		edges := vmsrest.NewReplicationEdgesList(vscr.Spec.ProtectionTopology, vscr.Spec.PrimaryStorageClass)
		tmpl := vmsrest.SpecTemplateToParams(vscr.Name, vscr.Spec.ProtectionPolicyTemplate)
		policyPairs, err := vmsrest.DiscoverLinkPolicies(restByStorageClass, scByStorageClass, edges, tmpl, log)
		if err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to ensure protection policies: %w", err)
		}

		ppathName, err = vmsrest.EnsureConstellationPpath(
			restByStorageClass, policyPairs, vscr.Spec.PrimaryStorageClass, vscr.Name, vscr.Status.PpathDirMapping, log,
		)
		if err != nil {
			emit.Warning(events.ReasonPpathNotReady, err.Error())
			return r.maybeBackoffRetry(bo, err, log)
		}

		vscr.Status.PpathName = ppathName
		if err := k8s.UpdateVastStorageClassReplicationStatus(ctx, vscr); err != nil {
			return ctrl.Result{}, err
		}
	}

	var errs cerrors.DeferredError
	// Use primary-first ordering so the primary VRC exists in the constellation
	// before any secondary VRC reconciles for the first time.
	allSCs := vscr.Spec.AllStorageClassesPrimaryFirst()
	for i, scName := range allSCs {
		vgrName, created, err := r.ensureVGR(ctx, emit, vscr, scName, ppathName, primaryChanged)
		if err != nil {
			errs.Add(fmt.Errorf("SC %s: %w", scName, err))
		}
		// When a VGR is freshly created, wait until the ReplicationObjectReconciler
		// has created the corresponding VRC before moving on to the next SC.
		// Secondary VRCs must find the primary VRC already present in the
		// constellation when they first reconcile so classifyConstellationPVCs
		// can locate the source PVCs and create the mirror PVCs.
		if created && i < len(allSCs)-1 {
			if waitErr := k8s.WaitForVRC(ctx, vscr.Namespace, vgrName, 30*time.Second); waitErr != nil {
				log.Warn(
					"proceeding without confirmed VRC",
					zap.String("vgr", vgrName),
					zap.Error(waitErr),
				)
			}
		}
	}

	if err := r.syncVGRReplicationStates(ctx, k8s, emit, vscr); err != nil {
		errs.Add(err)
	}

	if errs.Err() == nil {
		bo.Reset()
	}
	return r.maybeBackoffRetry(bo, errs.Err(), log)
}

// reconcileSyncStatus derives the desired SyncStatus from the overall
// reconcile result and the VolumeGroupReplication state, then persists it if
// it changed.  It swallows its own write errors so that the caller's original
// reconcile error is not masked.
func (r *VastStorageClassReplicationReconciler) reconcileSyncStatus(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	vscr *vastv1alpha1.VastStorageClassReplication,
	reconcileErr error,
) {
	var desired string

	switch {
	case vscr.GetDeletionTimestamp() != nil:
		desired = vastv1alpha1.SyncStatusDeleting
	case reconcileErr != nil && isNetworkError(reconcileErr):
		desired = vastv1alpha1.SyncStatusUnreachable
	case reconcileErr != nil && isValidationError(reconcileErr):
		desired = vastv1alpha1.SyncStatusInvalid
	case reconcileErr != nil:
		desired = vastv1alpha1.SyncStatusError
	default:
		vgrName := vgrNameForSC(vscr.Name, vscr.Spec.PrimaryStorageClass)
		vgr, err := k8s.GetVolumeGroupReplication(ctx, vgrName, vscr.Namespace)
		if err != nil {
			return
		}
		if vgr.Status.State == replicationv1alpha1.PrimaryState {
			desired = vastv1alpha1.SyncStatusCompleted
		} else {
			desired = vastv1alpha1.SyncStatusInProgress
		}
	}

	if vscr.Status.SyncStatus == desired {
		return
	}
	vscr.Status.SyncStatus = desired
	_ = k8s.UpdateVastStorageClassReplicationStatus(ctx, vscr)
}

func (r *VastStorageClassReplicationReconciler) validateOnce(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	vscr *vastv1alpha1.VastStorageClassReplication,
	restByStorageClass map[string]*vast_client.TypedVMSRest,
) error {
	if err := vscr.Spec.Validate(); err != nil {
		return cerrors.NewValidationError("%s", err.Error())
	}

	primarySC, err := k8s.GetStorageClass(ctx, vscr.Spec.PrimaryStorageClass)
	if err != nil {
		return fmt.Errorf("failed to get primary StorageClass %s: %w", vscr.Spec.PrimaryStorageClass, err)
	}

	if ppathdir.IsSubsystemLevel(k8s, primarySC) {
		// Subsystem-level block replication: VAST creates the subsystem on
		// secondary clusters via the replication stream itself.  If a user
		// pre-creates the subsystem on a secondary cluster, VAST replication
		// will fail with a conflict.  Detect this early and surface a clear
		// validation error.
		for _, scName := range vscr.Spec.AllStorageClasses() {
			if scName == vscr.Spec.PrimaryStorageClass {
				continue
			}
			sc, err := k8s.GetStorageClass(ctx, scName)
			if err != nil {
				return fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
			}
			scParams := k8s.ExtractNonPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
			scSubsystem := scParams[common.StorageClassParameterSubsystem]
			if scSubsystem == "" {
				return cerrors.NewValidationError("StorageClass %q is missing required parameter %q", scName, common.StorageClassParameterSubsystem)
			}

			if sc.Parameters["tenant_name"] == "" {
				return cerrors.NewValidationError(
					"subsystem-level block replication requires \"tenant_name\" parameter on secondary "+
						"StorageClass %q: the subsystem does not exist yet on secondary clusters "+
						"(VAST creates it via replication), so tenant resolution must use \"tenant_name\" directly",
					scName,
				)
			}

			rest := restByStorageClass[scName]
			exists, err := rest.Views.Exists(&typed.ViewSearchParams{
				RawData: vast_client.Params{
					"name":        scSubsystem,
					"tenant_name": sc.Parameters["tenant_name"],
				},
			})
			if err != nil {
				return fmt.Errorf("StorageClass %s: failed to check subsystem %q on secondary cluster: %w", scName, scSubsystem, err)
			}
			if exists {
				return cerrors.NewValidationError(
					"subsystem-level block replication requires that the subsystem %q does not pre-exist "+
						"on secondary cluster (StorageClass %q): VAST creates it via replication; "+
						"delete the subsystem from the secondary cluster and retry",
					scSubsystem, scName,
				)
			}
		}
	} else if k8sclient.IsBlockStorageClass(primarySC) {
		// Non-subsystem-level block VSCR: volumes are replicated within a
		// pre-existing subsystem.  The subsystem must be present on all clusters
		// before replication can start.
		for _, scName := range vscr.Spec.AllStorageClasses() {
			sc, err := k8s.GetStorageClass(ctx, scName)
			if err != nil {
				return fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
			}
			subsystemName := sc.Parameters[common.StorageClassParameterSubsystem]
			if subsystemName == "" {
				return cerrors.NewValidationError("StorageClass %q is missing required parameter %q", scName, common.StorageClassParameterSubsystem)
			}
			params := vast_client.Params{"name": subsystemName}
			if tn := sc.Parameters["tenant_name"]; tn != "" {
				params["tenant_name"] = tn
			}
			exists, err := restByStorageClass[scName].Views.Exists(&typed.ViewSearchParams{RawData: params})
			if err != nil {
				return fmt.Errorf("StorageClass %q: failed to check subsystem %q on cluster: %w", scName, subsystemName, err)
			}
			if !exists {
				return cerrors.NewValidationError(
					"StorageClass %q: subsystem %q does not exist on cluster; "+
						"for block replication the subsystem must be pre-created on all clusters",
					scName, subsystemName,
				)
			}
		}
	}

	return nil
}

func (r *VastStorageClassReplicationReconciler) handleDeletion(
	ctx context.Context,
	log *zap.Logger,
	emit *events.BoundReporter,
	vscr *vastv1alpha1.VastStorageClassReplication,
	bo *backoff.BoundBackoff,
) (ctrl.Result, error) {
	k8s := r.K8sFor(log)

	if !k8s.HasFinalizer(vscr, common.FinalizerVSCR) {
		return ctrl.Result{}, nil
	}

	for _, scName := range vscr.Spec.AllStorageClasses() {
		name := vgrNameForSC(vscr.Name, scName)
		if err := k8s.DeleteVolumeGroupReplication(ctx, name, vscr.Namespace); err != nil {
			return ctrl.Result{}, fmt.Errorf("failed to delete VolumeGroupReplication %s/%s: %w", vscr.Namespace, name, err)
		}
	}

	remainingVGRs := r.countOwnedVGRs(ctx, vscr)
	if remainingVGRs > 0 {
		log.Info("waiting for owned VolumeGroupReplications to be deleted",
			zap.Int("remaining", remainingVGRs))
		emit.Normalf(events.ReasonCleanupStarted,
			"waiting for %d owned VolumeGroupReplication(s) to be deleted before removing finalizer",
			remainingVGRs)
		return ctrl.Result{RequeueAfter: bo.Next()}, nil
	}

	// Also wait for all VastReplicationContents labelled with this VSCR to be
	// gone.  VRCs are owned by VGRs (not VSCR), so Kubernetes GC may not have
	// propagated DeletionTimestamp to them yet when the last VGR disappears.
	// Removing the VSCR finalizer before VRCs finish cleanup would cause their
	// lookupPrimaryStorageClass call to fail with "not found".
	vrcs, err := k8s.ListVastReplicationContentsByLabelSelector(ctx, vscr.Namespace,
		map[string]string{common.LabelSourceVSCR: vscr.Name})
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
	if vscr.Spec.PrimaryStorageClass != "" && vscr.Status.PpathName != "" {
		if rest, _, err := vmsrest.NewFromStorageClassName(ctx, k8s, vscr.Spec.PrimaryStorageClass, r.Config.SSLVerify, log); err == nil {
			ppath, _ := rest.ProtectedPaths.Get(&typed.ProtectedPathSearchParams{
				RawData: vast_client.Params{
					"name":   vscr.Status.PpathName,
					"fields": "id,name,enabled",
				},
			})
			if ppath != nil {
				if ppath.Enabled {
					rest.Untyped.ProtectedPaths.Update(ppath.Id, core.Params{"enabled": false})
				}
				if _, err := rest.ProtectedPaths.DeleteById(ppath.Id, 2*time.Minute); err != nil {
					log.With(zap.Error(err)).Info("failed to delete protected path for VastStorageClassReplication")
				}
			}
		}
	}

	// Delete the protection policies that were created for this VSCR.
	if vscr.Spec.PrimaryStorageClass != "" {
		vmsrest.DeleteProtectionPolicies(
			ctx, k8s,
			vscr.Name,
			vscr.Spec.PrimaryStorageClass,
			vscr.Spec.ProtectionTopology,
			r.Config.SSLVerify,
			log,
		)
	}

	if err := k8s.RemoveFinalizer(ctx, vscr, common.FinalizerVSCR); err != nil {
		return ctrl.Result{}, fmt.Errorf("failed to remove finalizer: %w", err)
	}
	log.Info("all owned VolumeGroupReplications and VastReplicationContents deleted, finalizer removed")
	return ctrl.Result{}, nil
}

func (r *VastStorageClassReplicationReconciler) countOwnedVGRs(
	ctx context.Context,
	vscr *vastv1alpha1.VastStorageClassReplication,
) int {
	count := 0
	for _, scName := range vscr.Spec.AllStorageClasses() {
		name := vgrNameForSC(vscr.Name, scName)
		if _, err := r.K8sClient.GetVolumeGroupReplication(ctx, name, vscr.Namespace); err == nil {
			count++
		}
	}
	return count
}

// ensureReplicationClasses creates (or no-ops) the VolumeReplicationClass and
// VolumeGroupReplicationClass for the given StorageClass.
func (r *VastStorageClassReplicationReconciler) ensureReplicationClasses(
	ctx context.Context,
	emit *events.BoundReporter,
	_ *vastv1alpha1.VastStorageClassReplication,
	scName string,
	ppathName string,
) (className string, err error) {
	k8s := r.K8sFor(emit.Logger())

	sc, err := k8s.GetStorageClass(ctx, scName)
	if err != nil {
		return "", fmt.Errorf("failed to get StorageClass %s: %w", scName, err)
	}

	className, err = provisioner.FormatReplicationClassName(ctx, k8s, provisioner.VSCRReplicationClassFormat, sc)
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

	vgrcBuilder := vbuilder.NewVolumeGroupReplicationClass(className, "").
		WithProvisioner(sc.Provisioner).
		WithParameter(common.CSIAddonsParamGroupReplicationSecretName, secretName).
		WithParameter(common.CSIAddonsParamGroupReplicationSecretNamespace, secretNamespace).
		WithParameter(common.ReplicationParamPpathName, ppathName).
		WithParameter(common.ReplicationParamStorageClass, scName).
		WithManagedByLabel()
	if subsystem != "" {
		vgrcBuilder = vgrcBuilder.WithParameter(common.ReplicationParamSubsystem, subsystem)
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

	vgrc := vgrcBuilder.Result()
	vgrcCreated, err := k8s.EnsureVolumeGroupReplicationClass(ctx, vgrc)
	if err != nil {
		return "", fmt.Errorf("failed to ensure VolumeGroupReplicationClass %s: %w", className, err)
	}
	if vgrcCreated {
		emit.Normalf(events.ReasonReplicationClassEnsured,
			"created VolumeGroupReplicationClass %s for StorageClass %q", className, scName)
	}

	return className, nil
}

// syncVGRReplicationStates resolves split-brain situations where multiple
// VolumeGroupReplications are simultaneously confirmed primary by csi-addons
// (Spec.ReplicationState == Primary AND Status.State == Primary).
//
// For each such candidate it queries the VAST cluster via REST to read the
// protected-path role.  The candidate whose ppath role is "source" is the true
// primary; all other confirmed-primary candidates are demoted to Secondary.
//
// If zero or one candidate exists, or if no candidate reports role "source"
// yet (VAST failover still in progress), the function is a no-op.
func (r *VastStorageClassReplicationReconciler) syncVGRReplicationStates(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
	vscr *vastv1alpha1.VastStorageClassReplication,
) error {
	// Collect every VGR that csi-addons considers primary.
	var candidates []string
	for _, scName := range vscr.Spec.AllStorageClasses() {
		vgr, err := k8s.GetVolumeGroupReplication(ctx, vgrNameForSC(vscr.Name, scName), vscr.Namespace)
		if err != nil {
			if k8serrors.IsNotFound(err) {
				// VGR not yet created (ensureVGR may have failed earlier); skip.
				continue
			}
			return fmt.Errorf("failed to get VolumeGroupReplication for SC %s: %w", scName, err)
		}
		if k8sclient.IsVGRConfirmedPrimary(vgr) {
			candidates = append(candidates, scName)
		}
	}

	truePrimarySC := vscr.Spec.PrimaryStorageClass
	var errs cerrors.DeferredError
	for _, scName := range candidates {
		if scName == truePrimarySC {
			continue
		}
		if err := r.ensureReplicationState(ctx, emit, vscr.Namespace, vgrNameForSC(vscr.Name, scName), scName, replicationv1alpha1.Secondary, false); err != nil {
			errs.Add(fmt.Errorf("SC %s: %w", scName, err))
		}
	}
	return errs.Err()
}

// ensureVGR creates or updates the VolumeGroupReplication for the given StorageClass.
// Returns (true, nil) when the VGR was freshly created, (false, nil) when it
// already existed, and (false, err) on error.
// primaryChanged must be true when the primary StorageClass switched this reconcile
// cycle so that an in-progress resync can be overridden with the failover state.
func (r *VastStorageClassReplicationReconciler) ensureVGR(
	ctx context.Context,
	emit *events.BoundReporter,
	vscr *vastv1alpha1.VastStorageClassReplication,
	scName string,
	ppathName string,
	primaryChanged bool,
) (vgrName string, created bool, err error) {
	k8s := r.K8sFor(emit.Logger())

	className, err := r.ensureReplicationClasses(ctx, emit, vscr, scName, ppathName)
	if err != nil {
		return "", false, err
	}

	vgrName = vgrNameForSC(vscr.Name, scName)

	state := replicationv1alpha1.Secondary
	if scName == vscr.Spec.PrimaryStorageClass {
		state = replicationv1alpha1.Primary
	}

	vgr, err := vbuilder.NewVolumeGroupReplication(vgrName, vscr.Namespace).
		WithLabelsMap(map[string]string{
			common.LabelManagedBy:    common.LabelManagedByValue,
			common.LabelStorageClass: scName,
		}).
		WithVolumeGroupReplicationClassName(className).
		WithVolumeReplicationClassName(className).
		WithReplicationState(state).
		WithAutoResync(true).
		WithSourceMatchLabels(map[string]string{common.LabelStorageClass: scName}).
		WithOwnerRef(vscr, k8s.Client().Scheme()).
		Build()
	if err != nil {
		return "", false, err
	}

	wasCreated, err := k8s.EnsureVolumeGroupReplication(ctx, vgr)
	if err != nil {
		return "", false, fmt.Errorf("failed to ensure VolumeGroupReplication %s/%s: %w", vscr.Namespace, vgrName, err)
	}
	if wasCreated {
		emit.Normalf(events.ReasonVolumeGroupReplicationCreated,
			"created VolumeGroupReplication %s/%s for StorageClass %q (replicationState=%s)",
			vscr.Namespace, vgrName, scName, state)
		return vgrName, true, nil
	}

	// Only drive the replicationState of the primary storage class.  Secondary
	// VGRs reflect the actual VAST ppath role via csi-addons Status.State, which
	// the VGR controller propagates into VastReplicationContent.
	if scName != vscr.Spec.PrimaryStorageClass {
		return vgrName, false, nil
	}
	return vgrName, false, r.ensureReplicationState(ctx, emit, vscr.Namespace, vgrName, scName, state, primaryChanged)
}

// ensureReplicationState syncs the replicationState of an existing VolumeGroupReplication
// to the desired state (e.g. after a primary StorageClass switch).
// primaryChanged must be true when the primary StorageClass switched this reconcile
// cycle so that an in-progress resync is overridden with the failover state.
func (r *VastStorageClassReplicationReconciler) ensureReplicationState(
	ctx context.Context,
	emit *events.BoundReporter,
	namespace, vgrName, scName string,
	desired replicationv1alpha1.ReplicationState,
	primaryChanged bool,
) error {
	k8s := r.K8sFor(emit.Logger())

	existing, err := k8s.GetVolumeGroupReplication(ctx, vgrName, namespace)
	if err != nil {
		return fmt.Errorf("failed to get VolumeGroupReplication %s/%s: %w", namespace, vgrName, err)
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
	if err := k8s.PatchVolumeGroupReplicationState(ctx, existing, desired); err != nil {
		return fmt.Errorf("failed to patch replicationState on VolumeGroupReplication %s/%s: %w",
			namespace, vgrName, err)
	}
	emit.Normalf(events.ReasonVolumeGroupReplicationUpdated,
		"updated VolumeGroupReplication %s/%s replicationState → %s (StorageClass %q)",
		namespace, vgrName, desired, scName)
	return nil
}

// vgrNameForSC returns the deterministic VGR name for a given VSCR + StorageClass pair.
func vgrNameForSC(vscrName, scName string) string {
	safe := strings.ReplaceAll(scName, ".", "-")
	return fmt.Sprintf("%s-%s", vscrName, safe)
}

func (r *VastStorageClassReplicationReconciler) ensureStorageClassPreview(vscr *vastv1alpha1.VastStorageClassReplication) bool {
	preview := vastv1alpha1.DisplayableList(vscr.Spec.AllStorageClasses()).String()
	if vscr.Status.StorageClassesPreview == preview {
		return false
	}
	vscr.Status.StorageClassesPreview = preview
	return true
}

func (r *VastStorageClassReplicationReconciler) ensurePrimaryStorageClass(vscr *vastv1alpha1.VastStorageClassReplication, emit *events.BoundReporter) bool {
	if vscr.Status.CurrentPrimaryStorageClass == vscr.Spec.PrimaryStorageClass {
		return false
	}
	old := vscr.Status.CurrentPrimaryStorageClass
	vscr.Status.CurrentPrimaryStorageClass = vscr.Spec.PrimaryStorageClass
	if old == "" {
		emit.Normalf("PrimaryStorageClassSet",
			"primary StorageClass set to %q", vscr.Spec.PrimaryStorageClass)
	} else {
		emit.Normalf("PrimaryStorageClassChanged",
			"primary StorageClass switched from %q to %q", old, vscr.Spec.PrimaryStorageClass)
	}
	return true
}

func (r *VastStorageClassReplicationReconciler) ensureLastFailoverType(vscr *vastv1alpha1.VastStorageClassReplication, emit *events.BoundReporter) bool {
	if vscr.Status.LastFailoverType == vscr.Spec.FailoverType {
		return false
	}
	old := vscr.Status.LastFailoverType
	vscr.Status.LastFailoverType = vscr.Spec.FailoverType
	if vscr.Spec.FailoverType != "" {
		if old == "" {
			emit.Normalf("FailoverTypeSet",
				"failoverType set to %q", vscr.Spec.FailoverType)
		} else {
			emit.Normalf("FailoverTypeChanged",
				"failoverType changed from %q to %q", old, vscr.Spec.FailoverType)
		}
	}
	return true
}

// ensureResync sets replicationState=resync on the primary VolumeGroupReplication
// and immediately clears Spec.Resync so it acts as a one-shot trigger.
func (r *VastStorageClassReplicationReconciler) ensureResync(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	emit *events.BoundReporter,
	vscr *vastv1alpha1.VastStorageClassReplication,
) error {
	vgrName := vgrNameForSC(vscr.Name, vscr.Spec.PrimaryStorageClass)
	existing, err := k8s.GetVolumeGroupReplication(ctx, vgrName, vscr.Namespace)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			// VGR not yet created — normal on first reconcile; clear the flag
			// so we don't loop.  The user can set Resync=true again once
			// provisioning has completed.
			emit.Logger().Info("resync skipped: VolumeGroupReplication not yet created; clearing Resync flag",
				zap.String("vgr", vgrName))
			return k8s.PatchVSCRResync(ctx, vscr)
		}
		return fmt.Errorf("ensureResync: failed to get VolumeGroupReplication %s/%s: %w", vscr.Namespace, vgrName, err)
	}
	if err := k8s.PatchVolumeGroupReplicationState(ctx, existing, replicationv1alpha1.Resync); err != nil {
		return fmt.Errorf("ensureResync: failed to patch replicationState on VolumeGroupReplication %s/%s: %w", vscr.Namespace, vgrName, err)
	}
	emit.Normalf("ResyncTriggered",
		"replicationState set to resync on VolumeGroupReplication %s/%s", vscr.Namespace, vgrName)

	if err := k8s.PatchVSCRResync(ctx, vscr); err != nil {
		return fmt.Errorf("ensureResync: failed to clear Resync flag on VSCR %s/%s: %w", vscr.Namespace, vscr.Name, err)
	}
	return nil
}

// SetupVastStorageClassReplicationController registers the reconciler with the manager.
func SetupVastStorageClassReplicationController(
	mgr ctrl.Manager,
	k8sClient *k8sclient.K8sClient,
	logger *zap.Logger,
	cfg *config.Config,
) error {
	base, err := NewBaseReconciler(mgr, k8sClient, logger, cfg, "vaststorageclassreplication")
	if err != nil {
		return err
	}
	r := &VastStorageClassReplicationReconciler{BaseReconciler: base}

	return ctrl.NewControllerManagedBy(mgr).
		For(&vastv1alpha1.VastStorageClassReplication{}).
		Owns(&replicationv1alpha1.VolumeGroupReplication{},
			builder.WithPredicates(ownedVGRPredicate())).
		Named("vaststorageclassreplication").
		Complete(r)
}
