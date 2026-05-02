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

package provisioner

import (
	"context"
	"fmt"
	"net/http"
	"path"
	"strings"
	"time"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/core"
	"github.com/vast-data/go-vast-client/resources/typed"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
	"github.com/vast-data/vast-csi/extensions-controller/internal/provisioner/builder"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/util/sets"
)

// VolumePair is a bound PVC together with its PV, pre-fetched to avoid
// redundant Kubernetes round-trips in downstream provisioning functions.
type VolumePair struct {
	PVC *corev1.PersistentVolumeClaim
	PV  *corev1.PersistentVolume
}

// pvcNames extracts the PVC name from each pair for use in log fields.
func pvcNames(pairs []VolumePair) []string {
	names := make([]string, len(pairs))
	for i, p := range pairs {
		names[i] = p.PVC.Name
	}
	return names
}

// baseProvisioner holds the fields and lifecycle helpers shared by all
// provisioner implementations.
type baseProvisioner struct {
	rp        *vastv1alpha1.VastReplicationContent
	k8sClient *k8s_client.K8sClient
	emit      *events.BoundReporter
	logger    *zap.Logger
	config    *config.Config

	sourceRest *vast_client.TypedVMSRest // pre-initialised VAST REST client for the source SC
	sourceSc   *storagev1.StorageClass   // source StorageClass, cached alongside sourceRest

	// primaryStorageClass is the StorageClass that the upstream VastStorageClassReplication
	// or VastVolumeReplication has designated as primary.
	primaryStorageClass string

	// ppathCache maps StorageClass name → fetched ProtectedPath, so each SC
	// pays at most one REST round-trip per provisioner lifetime.
	ppathCache map[string]*typed.ProtectedPathDetailsModel

	// toEnsure/toDelete are set by ProvisionVolumes so that ProvisionVolumeCb
	// implementations can access them without an extra parameter.  Provisioners
	// are per-reconcile instances, so this is safe from concurrent access.
	//
	// toEnsure holds pre-fetched VolumePairs (PVC+PV) to avoid redundant
	// Kubernetes lookups in downstream ensure functions.
	// toDelete holds source PVC names whose mirrors should be removed.
	toEnsure []VolumePair
	toDelete vastv1alpha1.PVCList

	self Interface // concrete provisioner embedding this base; set via setProvisioner
}

// setProvisioner stores the back-reference to the concrete provisioner.
// Must be called before initRest in every concrete constructor.
func (b *baseProvisioner) setProvisioner(self Interface) {
	b.self = self
}

// newBase initialises the common fields of a baseProvisioner.
func newBase(
	ctx context.Context,
	rp *vastv1alpha1.VastReplicationContent,
	k8sClient *k8s_client.K8sClient,
	emit *events.BoundReporter,
	cfg *config.Config,
) (*baseProvisioner, error) {
	rest, sc, err := vmsrest.NewFromStorageClassName(ctx, k8sClient, rp.Spec.StorageClass, cfg.SSLVerify, emit.Logger())
	if err != nil {
		return nil, err
	}

	primarySC, err := lookupPrimaryStorageClass(ctx, k8sClient, rp)
	if err != nil {
		return nil, err
	}

	return &baseProvisioner{
		rp:                  rp,
		k8sClient:           k8sClient,
		emit:                emit,
		logger:              emit.Logger(),
		config:              cfg,
		sourceRest:          rest,
		sourceSc:            sc,
		primaryStorageClass: primarySC,
		ppathCache:          make(map[string]*typed.ProtectedPathDetailsModel),
	}, nil
}

// lookupPrimaryStorageClass resolves the primaryStorageClass from the upstream
// VastStorageClassReplication or VastVolumeReplication that owns this VRC.
// Returns "" when the VRC has no upstream owner (standalone mode).
func lookupPrimaryStorageClass(ctx context.Context, k8s *k8s_client.K8sClient, rp *vastv1alpha1.VastReplicationContent) (string, error) {
	if vscrName := rp.Labels[common.LabelSourceVSCR]; vscrName != "" {
		vscr, err := k8s.GetVastStorageClassReplication(ctx, vscrName, rp.Namespace)
		if err != nil {
			return "", fmt.Errorf("get VastStorageClassReplication %s: %w", vscrName, err)
		}
		return vscr.Spec.PrimaryStorageClass, nil
	}
	if vvrName := rp.Labels[common.LabelSourceVVR]; vvrName != "" {
		vvr, err := k8s.GetVastVolumeReplication(ctx, vvrName, rp.Namespace)
		if err != nil {
			return "", fmt.Errorf("get VastVolumeReplication %s: %w", vvrName, err)
		}
		return vvr.Spec.PrimaryStorageClass, nil
	}
	panic("neither source VSCR not VVR exists")
}

// mirrorVolumeHandle computes the CSI volumeHandle for the static mirror PV
// that will be created on the destination (sibling) StorageClass cluster.
//
// For BLOCK StorageClasses the handle is subsystem-relative:
//	/[volumeGroup/]path.Base(sourceVolumeHandle)
//
// For FILE StorageClasses the handle is the full view path on the destination
// cluster, taken from the parent VSCR or VVR's PpathDirMapping (which
// encodes root_export[/volumeBaseName]).
func (b *baseProvisioner) mirrorVolumeHandle(
	ctx context.Context,
	sourcePV *corev1.PersistentVolume,
	sibSc *storagev1.StorageClass,
) (string, error) {
	volumeBaseName := path.Base(sourcePV.Spec.CSI.VolumeHandle)

	if k8s_client.IsBlockStorageClass(sibSc) {
		sibParams := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sibSc.Parameters)
		volumeGroup := strings.TrimPrefix(sibParams[common.StorageClassParameterVolumeGroup], "/")
		return path.Join("/", volumeGroup, volumeBaseName), nil
	}

	if vscrName := b.rp.Labels[common.LabelSourceVSCR]; vscrName != "" {
		vscr, err := b.k8sClient.GetVastStorageClassReplication(ctx, vscrName, b.rp.Namespace)
		if err != nil {
			return "", fmt.Errorf("get VastStorageClassReplication %s: %w", vscrName, err)
		}
		dir, ok := vscr.Status.PpathDirMapping[sibSc.Name]
		if !ok {
			return "", fmt.Errorf("StorageClass %q has no entry in VSCR %s PpathDirMapping", sibSc.Name, vscrName)
		}
		return path.Join(dir, volumeBaseName), nil
	}
	if vvrName := b.rp.Labels[common.LabelSourceVVR]; vvrName != "" {
		vvr, err := b.k8sClient.GetVastVolumeReplication(ctx, vvrName, b.rp.Namespace)
		if err != nil {
			return "", fmt.Errorf("get VastVolumeReplication %s: %w", vvrName, err)
		}
		dir, ok := vvr.Status.PpathDirMapping[sibSc.Name]
		if !ok {
			return "", fmt.Errorf("StorageClass %q has no entry in VVR %s PpathDirMapping", sibSc.Name, vvrName)
		}
		return dir, nil
	}

	return "", fmt.Errorf("VastReplicationContent %s/%s has neither %s nor %s label",
		b.rp.Namespace, b.rp.Name, common.LabelSourceVSCR, common.LabelSourceVVR)
}

// VolumeIDs implements VolumeMapper.  Returns a sorted list of bare volume
// names for the given StorageClass, derived from VolumeMapping.
func (b *baseProvisioner) VolumeIDs(ctx context.Context, sc *storagev1.StorageClass) ([]string, error) {
	mapping, err := b.self.(VolumeMapper).VolumeMapping(ctx, sc)
	if err != nil {
		return nil, err
	}
	return sortedKeys(mapping), nil
}

// VolumeCount implements VolumeMapper.  Returns the number of backend objects
// present for the given StorageClass.
func (b *baseProvisioner) VolumeCount(ctx context.Context, sc *storagev1.StorageClass) (int, error) {
	ids, err := b.self.(VolumeMapper).VolumeIDs(ctx, sc)
	if err != nil {
		return 0, err
	}
	return len(ids), nil
}

// hasVolume reports whether the full volume name / view path vol is present in
// the cached bulk listing for sc.  vol must already be the normalised full key
// (as returned by BackendObjectKey or constructed by ensureBlock/FileVastObject).
func (b *baseProvisioner) hasVolume(ctx context.Context, sc *storagev1.StorageClass, vol string) (bool, error) {
	mapping, err := b.self.(VolumeMapper).VolumeMapping(ctx, sc)
	if err != nil {
		return false, err
	}
	_, ok := mapping[strings.TrimRight(vol, "/")]
	return ok, nil
}

func (b *baseProvisioner) isVolumeGroup() bool {
	return b.rp.Spec.Kind == vastv1alpha1.DestinationKindVolumeGroupReplication
}

// ProvisionVolumes implements Interface.
func (b *baseProvisioner) ProvisionVolumes(ctx context.Context) error {
	var (
		errs                     cerrors.DeferredError
		isVolumeGroupReplication = b.isVolumeGroup()
		isPrimary                = b.rp.Spec.StorageClass == b.primaryStorageClass
	)
	// Pre-fetch and classify PVC+PV pairs for all constellation VRCs.
	// AllUnmanaged drives VAST object creation; OtherUnmanaged drives mirrors.
	unmanaged, err := b.classifyConstellationPVCs(ctx)
	if err != nil {
		return err
	}
	b.toEnsure = unmanaged

	// Compute which source PVCs were removed (status has more than spec) so
	// their backend objects and mirrors can be deleted.
	toDelete, err := b.computeSourceToDelete(ctx)
	if err != nil {
		return err
	}
	b.toDelete = toDelete

	// Sync VAST objects (views/quotas, block volumes) on own cluster.
	// We can sync VastObjects only for primary cluster.  Non-primary clusters are read-only
	// so you cannot create views, volumes etc whatsoever.
	if isPrimary && b.rp.Spec.SyncVastObjects {
		b.logger.Info("syncing VAST objects",
			zap.String("vrc", b.rp.Namespace+"/"+b.rp.Name),
			zap.String("storageClass", b.rp.Spec.StorageClass),
			zap.Bool("isVolumeGroup", isVolumeGroupReplication),
			zap.Strings("toEnsure", pvcNames(b.toEnsure)),
			zap.Strings("toDelete", b.toDelete),
		)
		if err := b.self.ProvisionVolumeCb(ctx, b.rp, b.sourceRest, b.sourceSc); err != nil {
			return err
		}
	}

	// Sync managed PVC+PV pairs on own cluster for sibling PVCs so workloads
	// can bind to the replicated volumes after a failover.
	// Filter AllUnmanaged to pairs from other storage classes (not self).
	if b.rp.Spec.SyncPVCPV {
		keepNames := sets.New[string]()
		var otherPairs []VolumePair
		for _, p := range unmanaged {
			if p.PVC.Spec.StorageClassName != nil && *p.PVC.Spec.StorageClassName == b.rp.Spec.StorageClass {
				continue // own cluster — no mirror needed
			}
			otherPairs = append(otherPairs, p)
			keepNames.Insert(p.PVC.Name)
		}
		b.logger.Info("syncing mirror PVCs",
			zap.String("vrc", b.rp.Namespace+"/"+b.rp.Name),
			zap.String("storageClass", b.rp.Spec.StorageClass),
			zap.String("primaryStorageClass", b.primaryStorageClass),
			zap.Bool("isPrimary", isPrimary),
			zap.Bool("isVolumeGroup", isVolumeGroupReplication),
			zap.Strings("siblings", pvcNames(otherPairs)),
		)
		if err := b.ensureReplicaMirrors(ctx, b.sourceSc, otherPairs); err != nil {
			errs.Add(fmt.Errorf("ensure mirrors: %w", err))
		}
		if err := b.cleanReplicaMirrorOrphans(ctx, b.rp, b.sourceSc, keepNames); err != nil {
			errs.Add(fmt.Errorf("orphan cleanup: %w", err))
		}
	}

	return errs.Err()
}

// classifyConstellationPVCs fetches PVC+PV pairs for every PVC across all
// constellation VRCs and partitions them into AllUnmanaged (CSI-created) and
// OtherUnmanaged (CSI-created, from sibling VRCs only).
//
// Controller-created mirror PVCs (LabelManagedBy present) are silently skipped
// so they can never recursively trigger further mirroring.
//
// An unbound PVC causes a RetryAfterError so the reconcile retries once bound.
func (b *baseProvisioner) classifyConstellationPVCs(ctx context.Context) ([]VolumePair, error) {
	vrcs, err := b.rp.GetConstellationVRCs(ctx, b.k8sClient.ListVastReplicationContentsByLabelSelector)
	if err != nil {
		return nil, fmt.Errorf("list constellation VastReplicationContents: %w", err)
	}
	var unmanaged []VolumePair
	for _, vrc := range vrcs {
		for _, pvcName := range vrc.Spec.PVCs {
			pvc, pv, bound, err := b.k8sClient.GetPVCandPV(ctx, pvcName, vrc.Namespace)
			if err != nil {
				if k8serrors.IsNotFound(err) {
					continue
				}
				return nil, fmt.Errorf("get PVC+PV %s/%s: %w", vrc.Namespace, pvcName, err)
			}
			if !bound {
				return nil, cerrors.NewRetryAfterError(
					fmt.Errorf("PVC %s/%s not yet bound", vrc.Namespace, pvcName),
					15*time.Second,
				)
			}
			if pvc.Labels[common.LabelManagedBy] == common.LabelManagedByValue {
				continue // skip controller-managed mirrors — anti-recursion guard
			}
			unmanaged = append(unmanaged, VolumePair{PVC: pvc, PV: pv})
		}
	}
	return unmanaged, nil
}

// computeSourceToDelete returns the non-managed source PVC names that were
// present in Status.PVCs but are no longer in Spec.PVCs.  These are source
// PVCs that were removed and whose managed mirrors must be cleaned up.
//
// PVCs that carry LabelManagedBy are controller mirrors — they are silently
// ignored here because status will be resynced on the next reconcile.
func (b *baseProvisioner) computeSourceToDelete(ctx context.Context) (vastv1alpha1.PVCList, error) {
	specSet := sets.New[string](b.rp.Spec.PVCs...)
	var toDelete vastv1alpha1.PVCList
	for _, pvcName := range b.rp.Status.PVCs {
		if specSet.Has(pvcName) {
			continue // still desired
		}
		pvc, err := b.k8sClient.GetPVC(ctx, pvcName, b.rp.Namespace)
		if err != nil {
			if k8serrors.IsNotFound(err) {
				// PVC gone — include so mirrors are cleaned up
				toDelete = append(toDelete, pvcName)
				continue
			}
			return nil, fmt.Errorf("get PVC %s/%s: %w", b.rp.Namespace, pvcName, err)
		}
		if pvc.Labels[common.LabelManagedBy] == common.LabelManagedByValue {
			continue // controller mirror — will disappear when status resyncs
		}
		toDelete = append(toDelete, pvcName)
	}
	return toDelete, nil
}

// CleanVolumes implements Interface.  Removes all resources owned by this VRC.
func (b *baseProvisioner) CleanVolumes(ctx context.Context) error {
	ppath, err := b.getPPathForSource(ctx)
	if err != nil {
		if !vast_client.IsNotFoundErr(err) {
			return err
		}
	} else if ppath != nil && ppath.Enabled {
		if _, err := b.sourceRest.Untyped.ProtectedPaths.Update(ppath.Id, core.Params{"enabled": false}); err != nil {
			return fmt.Errorf("failed to disable protected path %q: %w", ppath.Name, err)
		}
		b.emit.Normalf(events.ReasonPpathDisabled, "disabled protected path %q", ppath.Name)
		b.logger.Info("waiting for VMS to discover in-flight snapshots before deletion",
			zap.Duration("interval", common.VMS_SNAPSHOT_DISCOVERY_INTERVAL))
		time.Sleep(common.VMS_SNAPSHOT_DISCOVERY_INTERVAL)
	}
	if err := b.deleteReplicationSnapshots(ctx, b.sourceRest,
		b.rp.Spec.ReplicationPath, b.rp.Spec.ProtectionPolicyName); err != nil {
		return err
	}

	if ppath != nil {
		if _, err := b.sourceRest.ProtectedPaths.DeleteById(ppath.Id, 4*time.Minute); err != nil {
			if !vast_client.IsNotFoundErr(err) && !core.ExpectStatusCodes(err, http.StatusNotFound) {
				return fmt.Errorf("delete protected path %q: %w", ppath.Name, err)
			}
		} else {
			b.logger.Info("waiting for protected path to be deleted",
				zap.String("ppath", ppath.Name))
			if err := vmsrest.WaitForResource(
				b.sourceRest.Untyped.ProtectedPaths,
				core.Params{"name": ppath.Name},
				vmsrest.WaitConditionAbsent,
				2*time.Minute,
				15*time.Second,
				fmt.Sprintf("protected path %q", ppath.Name),
			); err != nil {
				return fmt.Errorf("waiting for protected path %q deletion: %w", ppath.Name, err)
			}
			b.emit.Normalf(events.ReasonPpathDeleted, "deleted protected path %q", ppath.Name)
		}
	}

	// Clean VAST objects on own cluster (views/quotas for file, block volumes).
	if err := b.self.CleanVolumeCb(ctx, b.rp, b.sourceRest, b.sourceSc); err != nil {
		return err
	}
	// Remove managed mirror PVCs/PVs on own cluster (nil = all are orphans).
	if err := b.cleanReplicaMirrorOrphans(ctx, b.rp, b.sourceSc, nil); err != nil {
		return err
	}

	return b.CleanKubernetesResources(ctx)
}

// CleanKubernetesResources implements Interface.  Dispatches cleanup based on Kind.
func (b *baseProvisioner) CleanKubernetesResources(ctx context.Context) error {
	storageClass := b.rp.Spec.StorageClass
	switch b.rp.Spec.Kind {
	case vastv1alpha1.DestinationKindVolumeReplication:
		return b.cleanVolumeReplication(ctx, storageClass)
	case vastv1alpha1.DestinationKindVolumeGroupReplication:
		return b.cleanVolumeGroupReplication(ctx, storageClass)
	default:
		return fmt.Errorf("unsupported kind %q", b.rp.Spec.Kind)
	}
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

// getPPath returns the VAST protected path for this RP's ProtectedPathName via
// a REST client derived from sc.  Results are cached per StorageClass name so
// each SC pays at most one REST round-trip per provisioner lifetime.
// Returns nil (no error) when ProtectedPathName is not yet populated.
func (b *baseProvisioner) getPPath(ctx context.Context, sc *storagev1.StorageClass) (*typed.ProtectedPathDetailsModel, error) {
	if cached, ok := b.ppathCache[sc.Name]; ok {
		return cached, nil
	}
	rest, err := vmsrest.NewFromStorageClass(ctx, b.k8sClient, sc, b.config.SSLVerify, b.logger)
	if err != nil {
		return nil, fmt.Errorf("build REST client for StorageClass %s: %w", sc.Name, err)
	}
	ppathName := b.rp.Spec.ProtectedPathName
	ppath, err := rest.ProtectedPaths.Get(&typed.ProtectedPathSearchParams{
		RawData: vast_client.Params{
			"name":   ppathName,
			"fields": "id,name,enabled,state,failure_reason,role,tenant_id,source_dir,protection_policy_name",
		},
	})
	if err != nil {
		return nil, err
	}
	b.ppathCache[sc.Name] = ppath
	return ppath, nil
}

// getPPathForSource is a convenience wrapper that fetches the protected path
// for the source StorageClass.
func (b *baseProvisioner) getPPathForSource(ctx context.Context) (*typed.ProtectedPathDetailsModel, error) {
	return b.getPPath(ctx, b.sourceSc)
}

// managedPVForPVC looks up the PV bound to pvc and returns it only when it
// carries the managed-by label.  Returns nil (no error) when the PV is not
// found or is not owned by this controller.
func (b *baseProvisioner) managedPVForPVC(ctx context.Context, pvc *corev1.PersistentVolumeClaim) (*corev1.PersistentVolume, error) {
	if pvc.Spec.VolumeName == "" {
		return nil, nil
	}
	pvObj, err := b.k8sClient.GetPV(ctx, pvc.Spec.VolumeName)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			b.logger.Info("PV not found, skipping PV deletion", zap.String("pv", pvc.Spec.VolumeName))
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get PV %s: %w", pvc.Spec.VolumeName, err)
	}
	if val, _ := b.k8sClient.GetLabel(pvObj, common.LabelManagedBy); val == common.LabelManagedByValue {
		return pvObj, nil
	}
	return nil, nil
}

// ---------------------------------------------------------------------------
// Delete helpers
// ---------------------------------------------------------------------------

// deleteSnapshots deletes all replication snapshots matching snapshotPath and ppolicyName.
func (b *baseProvisioner) deleteSnapshots(_ context.Context, rest *vast_client.TypedVMSRest, snapshotPath, ppolicyName string) error {
	snapshotPath = strings.TrimRight(snapshotPath, "/") + "/"
	snapshotSearch := &typed.SnapshotSearchParams{
		RawData: vast_client.Params{
			"path":                    snapshotPath,
			"protection_policy__name": ppolicyName,
		},
	}
	snapshots, err := rest.Snapshots.List(snapshotSearch)
	if err != nil {
		return fmt.Errorf("failed to list snapshots for path %s: %w", snapshotPath, err)
	}
	for _, snapshot := range snapshots {
		if err := vast_client.IgnoreStatusCodes(rest.Snapshots.DeleteById(snapshot.Id), 404); err != nil {
			b.emit.Warningf(events.ReasonCleanupFailed,
				"failed to delete snapshot %s: %v", snapshot.Name, err)
		} else {
			b.emit.Normalf(events.ReasonSnapshotsDeleted, "deleted snapshot %s", snapshot.Name)
		}
	}
	return nil
}

// deleteReplicationSnapshots deletes snapshots under replicationPath.
// Returns early without error when the required fields are not yet populated.
func (b *baseProvisioner) deleteReplicationSnapshots(
	ctx context.Context,
	rest *vast_client.TypedVMSRest,
	replicationPath, protectionPolicyName string,
) error {
	return vast_client.IgnoreStatusCodes(b.deleteSnapshots(ctx, rest, replicationPath, protectionPolicyName), 404)
}

// ---------------------------------------------------------------------------
// Constellation PVC/PV mirroring
//
// A "constellation" is the set of all VastReplicationContent (VRC) objects that
// belong to the same top-level replication object (VastStorageClassReplication
// or VastVolumeReplication).  Within a constellation each VRC owns a distinct
// StorageClass.
//
// Each VRC reconcile is self-contained:
//   - The primary VRC creates VAST backend objects (views/quotas or block
//     volumes) on its own cluster.
//   - Each secondary VRC reads the primary VRC's PVC list from Kubernetes
//     (no VAST API call required) and ensures a mirrored static PVC+PV exists
//     on its own StorageClass for every source PVC the primary owns.
//
// The mirrored PVC uses the same volume handle as the source PV because VAST
// replication preserves volume paths on the destination cluster.
//
// Anti-recursion: source PVCs are identified by the ABSENCE of the managed-by
// label (LabelManagedBy = LabelManagedByValue).  Once a PVC carries that label
// it is treated as a mirror and will not trigger further mirroring.

// ensureReplicaMirrors creates (or verifies) a managed mirror PVC+PV on
// sc's StorageClass for every pre-fetched source VolumePair in pairs.
// The PVC+PV are already fetched so no extra Kubernetes round-trips are needed.
func (b *baseProvisioner) ensureReplicaMirrors(
	ctx context.Context,
	sc *storagev1.StorageClass,
	pairs []VolumePair,
) error {

	var (
		errs           cerrors.DeferredError
		alreadyExisted []string
		isVolumeGroup  = b.isVolumeGroup()
	)
	for _, pair := range pairs {
		// For VolumeGroupReplication (VSCR) gate mirror creation on the VAST
		// backend object being present on the destination cluster: volumes are
		// replicated asynchronously and may not exist there yet.
		// For VolumeReplication (VVR) always create the mirror PVC regardless —
		// the PVC must exist before csi-addons can track the replicated copy,
		// and waiting for the backend object would break failover sequencing.
		if b.rp.Spec.SyncVastObjects && isVolumeGroup && b.self.ShouldGateMirrorOnBackend() {
			key := b.self.(VolumeMapper).BackendObjectKey(pair.PV.Spec.CSI.VolumeHandle)
			exists, err := b.hasVolume(ctx, sc, key)
			if err != nil {
				if common.IsNetworkError(err) {
					b.emit.Warningf(events.ReasonProvisionSkipped,
						"cluster %s is unreachable, skipping mirror PVC/PV sync: %v", sc.Name, err)
					// Networking failure is cluster-wide — no point continuing for other PVCs.
					return nil
				}
				return err
			}
			if !exists {
				b.emit.Warningf(events.ReasonProvisionSkipped,
					"VAST backend object for PV %s not yet present on cluster %s, skipping mirror creation",
					pair.PV.Name, sc.Name,
				)
				continue
			}
		}

		created, err := b.ensureMirrorPVCPV(ctx, pair.PVC, pair.PV, sc)
		if err != nil {
			errs.Add(fmt.Errorf("mirror %s → %s: %w", pair.PVC.Name, sc.Name, err))
			continue
		}
		if !created {
			alreadyExisted = append(alreadyExisted, pair.PVC.Name)
		}
	}
	if len(alreadyExisted) > 0 {
		b.logger.Info("mirror PVC+PV already exist, skipping creation",
			zap.Strings("pvcs", alreadyExisted))
	}
	return errs.Err()
}

// ensureMirrorPVCPV creates a static PV+PVC pair in sibSc's StorageClass
// that mirrors sourcePVC.  The PV's volume handle is taken directly from sourcePV
// because VAST replication preserves volume paths on the destination cluster.
// ensureMirrorPVCPV returns (true, nil) when the mirror PV+PVC was freshly
// created, (false, nil) when both already existed, and (false, err) on error.
func (b *baseProvisioner) ensureMirrorPVCPV(
	ctx context.Context,
	sourcePVC *corev1.PersistentVolumeClaim,
	sourcePV *corev1.PersistentVolume,
	sibSc *storagev1.StorageClass,
) (bool, error) {
	if sourcePV.Spec.CSI == nil || sourcePV.Spec.CSI.VolumeHandle == "" {
		return false, fmt.Errorf("source PV %s has no CSI volume handle", sourcePV.Name)
	}
	ns := sourcePVC.Namespace

	destPVCName, err := FormatPVCName(ctx, b.k8sClient, b.config.PVCNameFormat, sourcePVC, sourcePV, sibSc)
	if err != nil {
		return false, fmt.Errorf("format mirror PVC name: %w", err)
	}
	destPVName, err := FormatPVName(ctx, b.k8sClient, b.config.PVNameFormat, sourcePVC, sourcePV, sibSc)
	if err != nil {
		return false, fmt.Errorf("format mirror PV name: %w", err)
	}

	csiSecrets := b.k8sClient.ExtractPrefixedParams(common.CSIParameterPrefix, sibSc.Parameters)
	secretName := csiSecrets["provisioner-secret-name"]
	secretNS := csiSecrets["provisioner-secret-namespace"]
	if secretName == "" || secretNS == "" {
		return false, fmt.Errorf("StorageClass %s is missing provisioner secret parameters", sibSc.Name)
	}
	secretRef := &corev1.SecretReference{Name: secretName, Namespace: secretNS}
	csiDriver := sourcePV.Spec.CSI.Driver
	if csiDriver == "" {
		return false, fmt.Errorf("source PV %s has no CSI driver", sourcePV.Name)
	}
	capacity := sourcePV.Spec.Capacity
	if len(capacity) == 0 {
		return false, fmt.Errorf("source PV %s has no capacity", sourcePV.Name)
	}

	// volumeAttributes must carry the VAST-specific (non-prefixed) parameters
	// such as subsystem, vip_pool_name, volume_group, etc.
	volumeAttrs := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sibSc.Parameters)

	mirrorHandle, err := b.mirrorVolumeHandle(ctx, sourcePV, sibSc)
	if err != nil {
		return false, fmt.Errorf("compute mirror volume handle: %w", err)
	}

	pvLabels := map[string]string{
		common.LabelManagedBy:          common.LabelManagedByValue,
		common.LabelSourcePVC:          sourcePVC.Name,
		common.LabelSourcePVCNamespace: sourcePVC.Namespace,
	}
	pvcLabels := map[string]string{
		common.LabelManagedBy:          common.LabelManagedByValue,
		common.LabelStorageClass:       sibSc.Name,
		common.LabelSourcePVC:          sourcePVC.Name,
		common.LabelSourcePVCNamespace: sourcePVC.Namespace,
	}
	// Propagate the upstream VSCR/VVR reference from the VRC onto the mirror
	// PVC so that the PVCRemapReconciler can scope its ListPVCsByLabelSelector
	// query (used by the VVR path) to the correct owner.
	if vscrName := b.rp.Labels[common.LabelSourceVSCR]; vscrName != "" {
		pvcLabels[common.LabelSourceVSCR] = vscrName
	}
	if vvrName := b.rp.Labels[common.LabelSourceVVR]; vvrName != "" {
		pvcLabels[common.LabelSourceVVR] = vvrName
	}

	pvBuilder := builder.NewPersistentVolume(destPVName).
		WithFinalizers(common.FinalizerPV).
		WithManagedByLabel().
		WithLabelsMap(pvLabels).
		WithStorageClass(sibSc.Name).
		WithVolumeHandle(mirrorHandle).
		WithCSIDriver(csiDriver).
		WithVolumeAttributes(volumeAttrs).
		WithReclaimPolicy(corev1.PersistentVolumeReclaimRetain).
		WithAccessModes(sourcePV.Spec.AccessModes...).
		WithCapacity(capacity).
		WithControllerPublishSecretRef(secretRef).
		WithNodeStageSecretRef(secretRef).
		WithNodePublishSecretRef(secretRef).
		WithControllerExpandSecretRef(secretRef)
	if sourcePV.Spec.VolumeMode != nil {
		pvBuilder = pvBuilder.WithVolumeMode(*sourcePV.Spec.VolumeMode)
	}
	destPV := pvBuilder.Result()

	pvCreated, err := b.k8sClient.EnsurePV(ctx, destPV)
	if err != nil {
		return false, fmt.Errorf("ensure mirror PV %s: %w", destPVName, err)
	}

	pvcBuilder := builder.NewPersistentVolumeClaim(ns, destPVCName).
		WithManagedByLabel().
		WithLabelsMap(pvcLabels).
		WithFinalizers(common.FinalizerPVC).
		WithStorageClass(sibSc.Name).
		WithVolumeName(destPVName).
		WithAccessModes(sourcePV.Spec.AccessModes...).
		WithResources(capacity)
	if sourcePV.Spec.VolumeMode != nil {
		pvcBuilder = pvcBuilder.WithVolumeMode(*sourcePV.Spec.VolumeMode)
	}
	destPVC := pvcBuilder.Result()

	pvcCreated, err := b.k8sClient.EnsurePVC(ctx, destPVC)
	if err != nil {
		return false, fmt.Errorf("ensure mirror PVC %s/%s: %w", ns, destPVCName, err)
	}

	created := pvCreated || pvcCreated
	if created {
		b.emit.Normalf(events.ReasonPVCPVCreated,
			"created mirror PVC+PV for %s/%s → StorageClass %q (pvc=%s, pv=%s)",
			ns, sourcePVC.Name, sibSc.Name, destPVCName, destPVName)
	}
	return created, nil
}

// cleanReplicaMirrorOrphans removes mirrored PVCs+PVs in StorageClass that
// were created by this VRC but whose source PVC is no longer in currentSourcePVCNames.
// Passing nil or empty removes ALL mirrors owned by this VRC for the given peer.
func (b *baseProvisioner) cleanReplicaMirrorOrphans(
	ctx context.Context,
	vrc *vastv1alpha1.VastReplicationContent,
	sc *storagev1.StorageClass,
	currentSourcePVCNames sets.Set[string],
) error {
	ns := b.rp.Namespace

	pvcs, err := b.k8sClient.ListPVCsByLabelSelector(ctx, ns, map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelStorageClass: sc.Name,
	})
	if err != nil {
		return fmt.Errorf("failed to list mirror PVCs for %s: %w", vrc.Name, err)
	}
	if len(pvcs) == 0 {
		return nil
	}

	var errs cerrors.DeferredError
	for i := range pvcs {
		pvc := &pvcs[i]
		sourcePVCName, _ := b.k8sClient.GetLabel(pvc, common.LabelSourcePVC)
		if currentSourcePVCNames.Has(sourcePVCName) {
			continue // still valid — keep it
		}
		b.logger.Info("deleting orphaned mirror PVC",
			zap.String("mirrorPVC", pvc.Name),
			zap.String("sourcePVC", sourcePVCName))

		pv, pvErr := b.managedPVForPVC(ctx, pvc)
		if pvErr != nil {
			b.logger.Warn("could not find managed PV for orphaned mirror PVC",
				zap.String("pvc", pvc.Name), zap.Error(pvErr))
		}
		if err := b.k8sClient.ClearFinalizers(ctx, pvc); err != nil {
			errs.Add(fmt.Errorf("delete orphaned mirror PVC %s: clear finalizers: %w", pvc.Name, err))
			continue
		}
		if err := b.k8sClient.Client().Delete(ctx, pvc); err != nil {
			if !k8serrors.IsNotFound(err) {
				errs.Add(fmt.Errorf("delete orphaned mirror PVC %s: %w", pvc.Name, err))
				continue
			}
		} else {
			b.emit.Normalf(events.ReasonPVCDeleted, "deleted orphaned mirror PVC %s/%s", pvc.Namespace, pvc.Name)
		}
		if pv != nil {
			if err := b.k8sClient.ClearFinalizers(ctx, pv); err != nil {
				errs.Add(fmt.Errorf("delete orphaned mirror PV for %s: clear finalizers: %w", pvc.Name, err))
				continue
			}
			if err := b.k8sClient.Client().Delete(ctx, pv); err != nil {
				if !k8serrors.IsNotFound(err) {
					errs.Add(fmt.Errorf("delete orphaned mirror PV for %s: %w", pvc.Name, err))
				}
			} else {
				b.emit.Normalf(events.ReasonPVDeleted, "deleted orphaned mirror PV %s", pv.Name)
			}
		}
	}
	return errs.Err()
}

// cleanVolumeReplication deletes all destination resources (PVCs, PVs,
// VolumeReplication CRDs) created for this ReplicationProvision's source.
// When storageClass is non-empty only resources for that specific StorageClass are removed.
func (b *baseProvisioner) cleanVolumeReplication(ctx context.Context, storageClass string) error {
	namespace := b.rp.Namespace
	sourceVRName := b.rp.SourceName()
	labelSelector := map[string]string{
		common.LabelManagedBy:                        common.LabelManagedByValue,
		common.LabelSourceVolumeReplication:          sourceVRName,
		common.LabelSourceVolumeReplicationNamespace: namespace,
	}
	if storageClass != "" {
		labelSelector[common.LabelStorageClass] = storageClass
	}
	b.emit.Normalf(events.ReasonCleanupStarted,
		"cleaning up resources for VolumeReplication %s/%s", namespace, sourceVRName)

	destVRs, err := b.k8sClient.ListVolumeReplicationsByLabelSelector(ctx, namespace, labelSelector)
	if err != nil {
		return fmt.Errorf("failed to list VolumeReplications: %w", err)
	}

	// csi-addons adds replication.storage.openshift.io/vr-protection to every PVC
	// that belongs to a VR and only removes it while processing the VR's own deletion.
	// We must therefore wait until all managed VRs are fully gone before deleting PVCs;
	// otherwise PVCs get stuck in Terminating indefinitely.
	if len(destVRs) > 0 {
		for _, destVR := range destVRs {
			b.emit.Normalf(events.ReasonVolumeReplicationDeleted,
				"deleting destination VolumeReplication %s (source=%s)", destVR.Name, sourceVRName)
			if err := b.k8sClient.Client().Delete(ctx, &destVR); err != nil && !k8serrors.IsNotFound(err) {
				b.emit.Warningf(events.ReasonCleanupFailed,
					"failed to delete destination VolumeReplication %s: %v", destVR.Name, err)
			}
		}
		return fmt.Errorf(
			"waiting for %d managed VolumeReplication(s) to be fully deleted before cleaning PVCs "+
				"(source=%s/%s)", len(destVRs), namespace, sourceVRName)
	}

	return nil

}

// cleanVolumeGroupReplication deletes all destination resources (PVCs, PVs,
// VolumeGroupReplication CRDs) created for this ReplicationProvision's source.
// When storageClass is non-empty only resources for that specific StorageClass are removed.
func (b *baseProvisioner) cleanVolumeGroupReplication(ctx context.Context, storageClass string) error {
	namespace := b.rp.Namespace
	sourceVGRName := b.rp.SourceName()
	labelSelector := map[string]string{
		common.LabelManagedBy:                             common.LabelManagedByValue,
		common.LabelSourceVolumeGroupReplication:          sourceVGRName,
		common.LabelSourceVolumeGroupReplicationNamespace: namespace,
	}
	if storageClass != "" {
		labelSelector[common.LabelStorageClass] = storageClass
	}

	b.emit.Normalf(events.ReasonCleanupStarted,
		"cleaning up resources for VolumeGroupReplication %s/%s", namespace, sourceVGRName)

	destVGRs, err := b.k8sClient.ListVolumeGroupReplicationsByLabelSelector(ctx, namespace, labelSelector)
	if err != nil {
		return fmt.Errorf("failed to list VolumeGroupReplications: %w", err)
	}

	// csi-addons adds replication.storage.openshift.io/vgr-protection to every PVC
	// that belongs to a VGR and only removes it while processing the VGR's own deletion.
	// We must wait until all managed VGRs are fully gone before deleting PVCs; otherwise
	// PVCs get stuck in Terminating indefinitely because csi-addons' finalizer is still present.
	// Returning an error here causes the RP reconciler to requeue until VGRs disappear.
	if len(destVGRs) > 0 {
		for _, destVGR := range destVGRs {
			b.emit.Normalf(events.ReasonVolumeGroupReplicationDeleted,
				"deleting destination VolumeGroupReplication %s (source=%s)", destVGR.Name, sourceVGRName)
			if err := b.k8sClient.Client().Delete(ctx, &destVGR); err != nil && !k8serrors.IsNotFound(err) {
				return err
			}
		}
		return fmt.Errorf(
			"waiting for %d managed VolumeGroupReplication(s) to be fully deleted before cleaning PVCs "+
				"(source=%s/%s)", len(destVGRs), namespace, sourceVGRName)
	}
	return nil

}
