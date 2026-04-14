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
	"path"
	"strconv"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"
)

// BlockProvisioner creates block Volumes on the VAST cluster.
type BlockProvisioner struct {
	*baseProvisioner

	volumeCaches lazyCacheMap[map[string]any]
}

// NewBlockProvisioner creates a new BlockProvisioner for the given ReplicationProvision.
func NewBlockProvisioner(ctx context.Context, rp *vastv1alpha1.VastReplicationContent, k8sClient *k8s_client.K8sClient, emit *events.BoundReporter, cfg *config.Config) (*BlockProvisioner, error) {
	base, err := newBase(ctx, rp, k8sClient, emit, cfg)
	if err != nil {
		return nil, err
	}
	p := &BlockProvisioner{baseProvisioner: base}
	base.setProvisioner(p)
	return p, nil
}

// VolumeMapping implements VolumeMapper.  Returns a map of bare volume name →
// *typed.VolumeDetailsModel (stored as any) for the given StorageClass.
// Results are cached per StorageClass name.
func (b *BlockProvisioner) VolumeMapping(ctx context.Context, sc *storagev1.StorageClass) (map[string]any, error) {
	return b.volumeCaches.get(sc.Name, func() (map[string]any, error) {
		rest, err := vmsrest.NewFromStorageClass(ctx, b.k8sClient, sc, b.config.SSLVerify, b.logger)
		if err != nil {
			return nil, err
		}
		sibParams := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
		srcParams := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, b.sourceSc.Parameters)
		subsystemName := sibParams[common.StorageClassParameterSubsystem]
		volumeGroup := strings.TrimPrefix(srcParams[common.StorageClassParameterVolumeGroup], "/")

		fields := "id,name"
		var volumeSearch typed.VolumeSearchParams
		if volumeGroup == "" {
			volumeSearch = typed.VolumeSearchParams{
				RawData: vast_client.Params{
					"subsystem_name": subsystemName,
					"fields":         fields,
				},
			}
		} else {
			volumeSearch = typed.VolumeSearchParams{
				RawData: vast_client.Params{
					"subsystem_name": subsystemName,
					"name__contains": volumeGroup,
					"fields":         fields,
				},
			}
		}
		result, err := rest.Volumes.List(&volumeSearch)
		if err != nil {
			return nil, err
		}
		m := make(map[string]any, len(result))
		for _, vol := range result {
			m[strings.TrimRight(vol.Name, "/")] = vol
		}
		return m, nil
	})
}

// getVolume returns the cached *typed.VolumeDetailsModel for the full volume
// name vol (e.g. "group/pvc-123"), or nil if absent.
func (b *BlockProvisioner) getVolume(ctx context.Context, sc *storagev1.StorageClass, vol string) (*typed.VolumeDetailsModel, error) {
	mapping, err := b.VolumeMapping(ctx, sc)
	if err != nil {
		return nil, err
	}
	v, ok := mapping[strings.TrimRight(vol, "/")]
	if !ok {
		return nil, nil
	}
	return v.(*typed.VolumeDetailsModel), nil
}

func (b *BlockProvisioner) ShouldGateMirrorOnBackend() bool { return false }

// BackendObjectKey implements VolumeMapper.  Returns the full volume name used
// as a key in VolumeMapping: volumeGroup/volId (or just volId when no group).
func (b *BlockProvisioner) BackendObjectKey(volumeHandle string) string {
	if strings.HasPrefix(volumeHandle, "/") {
		return strings.TrimPrefix(volumeHandle, "/")
	}
	srcParams := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, b.sourceSc.Parameters)
	volumeGroup := strings.TrimPrefix(srcParams[common.StorageClassParameterVolumeGroup], "/")
	return strings.TrimRight(path.Join(volumeGroup, volumeHandle), "/")
}

// ---------------------------------------------------------------------------
// ProvisionStep: syncVastObjects
// ---------------------------------------------------------------------------

// ProvisionVolumeCb implements Interface.  Called by ProvisionVolumes for this VRC's own cluster.
// Ensures VAST block volumes exist on this VRC's own cluster and removes them for
// PVCs no longer in the source list.
func (b *BlockProvisioner) ProvisionVolumeCb(ctx context.Context, sibVRC *vastv1alpha1.VastReplicationContent, sibRest *vast_client.TypedVMSRest, sibSc *storagev1.StorageClass) error {
	ppath, err := b.getPPath(ctx, sibSc)
	if err != nil {
		return err
	}
	// When the peer is the replication Destination its VAST block volumes are
	// managed by VAST itself (replicated from the Source).  Nothing for us to
	// create here; silently skip.
	if isDestinationRole(ppath.Role) {
		return nil
	}
	return b.syncBlockObjects(ctx, sibRest, sibSc, sibVRC, ppath, b.toEnsure, b.toDelete)
}

// CleanVolumeCb implements Interface.  Called by CleanVolumes for this VRC's own cluster.
// Deletes VAST block volumes for all PVCs on this VRC's own cluster.
// Mirror PVC/PV removal is handled separately by cleanOrphansCb, which runs
// after this callback; the ordering ensures volume handles are still
// resolvable via the mirror PVC's bound PV at the time they are cleaned up.
func (b *BlockProvisioner) CleanVolumeCb(ctx context.Context, _ *vastv1alpha1.VastReplicationContent, sibRest *vast_client.TypedVMSRest, sibSc *storagev1.StorageClass) error {
	if !b.rp.Spec.SyncVastObjects {
		return nil
	}
	pvcs, err := b.k8sClient.ListPVCsByLabelSelector(ctx, b.rp.Namespace, map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelStorageClass: sibSc.Name,
	})
	if err != nil {
		return fmt.Errorf("list managed mirror PVCs for %s: %w", sibSc.Name, err)
	}
	var errs cerrors.DeferredError
	for i := range pvcs {
		pvc := &pvcs[i]
		pv, pvErr := b.managedPVForPVC(ctx, pvc)
		if pvErr != nil {
			errs.Add(pvErr)
			continue
		}
		if pv == nil || pv.Spec.CSI == nil || pv.Spec.CSI.VolumeHandle == "" {
			continue
		}
		volumeName := b.BackendObjectKey(pv.Spec.CSI.VolumeHandle)
		if err := b.deleteVastVolumeByName(ctx, sibRest, sibSc, volumeName); err != nil {
			errs.Add(err)
			continue
		}
		b.emit.Normalf(events.ReasonVASTVolumeDeleted, "deleted VAST block volume %s for mirror PVC %s", volumeName, pvc.Name)
	}
	return errs.Err()
}

// syncBlockObjects creates or deletes VAST block volumes on this VRC's own
// cluster.  toEnsure holds pre-fetched VolumePairs so no redundant K8s
// lookups are needed.  toDelete holds source PVC names whose associated
// managed mirror volumes should be removed.
func (b *BlockProvisioner) syncBlockObjects(
	ctx context.Context,
	sibRest *vast_client.TypedVMSRest,
	sibSc *storagev1.StorageClass,
	sibVRC *vastv1alpha1.VastReplicationContent,
	ppath *typed.ProtectedPathDetailsModel,
	toEnsure []VolumePair, toDelete vastv1alpha1.PVCList,
) error {
	sibParams := b.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sibSc.Parameters)
	subsystemName := sibParams[common.StorageClassParameterSubsystem]
	qosPolicyId := sibParams[common.StorageClassParameterQosPolicyId]

	var errs cerrors.DeferredError

	if len(toEnsure) > 0 {
		// Fetch the subsystem once for all PVCs in this group.
		subsystem, err := sibRest.Views.Get(&typed.ViewSearchParams{
			RawData: vast_client.Params{
				"name":      subsystemName,
				"tenant_id": ppath.TenantId,
				"fields":    "id,name,path,tenant_id",
			},
		})
		if err != nil {
			return fmt.Errorf("get subsystem %s on %s: %w", subsystemName, sibVRC.Name, err)
		}
		if !strings.HasPrefix(ppath.SourceDir, subsystem.Path) {
			return fmt.Errorf(
				"protected path source dir %q does not match subsystem path %q on %s",
				ppath.SourceDir, subsystem.Path, sibVRC.Name,
			)
		}

		for _, pair := range toEnsure {
			if err := b.ensureBlockVastVolume(ctx, sibRest, sibSc, pair, qosPolicyId,
				subsystem.Id); err != nil {
				errs.Add(fmt.Errorf("sync VAST volume for %s: %w", pair.PVC.Name, err))
			}
		}
	}

	for _, pvcName := range toDelete {
		if err := b.deleteBlockVastVolume(ctx, sibRest, sibSc, pvcName); err != nil {
			errs.Add(fmt.Errorf("delete VAST volume for source %s: %w", pvcName, err))
		}
	}
	return errs.Err()
}

// ensureBlockVastVolume ensures a VAST block volume exists for the given source
// PVC on this VRC's own cluster.  Existence is checked via the cached VolumeMapping
// so no per-volume REST round-trip is needed.
// The PVC and PV are already fetched in pair — no redundant K8s lookup.
func (b *BlockProvisioner) ensureBlockVastVolume(
	ctx context.Context,
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
	pair VolumePair,
	qosPolicyId string,
	viewId int64,
) error {
	sourcePVC := pair.PVC
	sourcePV := pair.PV
	volumeName := b.BackendObjectKey(sourcePV.Spec.CSI.VolumeHandle)

	exists, err := b.hasVolume(ctx, sc, volumeName)
	if err != nil {
		return err
	}

	if exists {
		return nil
	}
	storageRequest, found := sourcePVC.Spec.Resources.Requests[corev1.ResourceStorage]
	if !found {
		return fmt.Errorf("PVC %s/%s has no storage request", sourcePVC.Namespace, sourcePVC.Name)
	}
	volumeData := &typed.VolumeRequestBody{
		Name:   volumeName,
		ViewId: viewId,
		Size:   storageRequest.Value(),
	}
	if qosPolicyId != "" {
		id, err := strconv.Atoi(qosPolicyId)
		if err != nil {
			return fmt.Errorf("invalid qos_policy_id %q: %w", qosPolicyId, err)
		}
		volumeData.QosPolicyId = int64(id)
	}
	created, err := rest.Volumes.Create(volumeData)
	if err != nil {
		return fmt.Errorf("create VAST volume %s: %w", volumeName, err)
	}
	b.volumeCaches.add(sc.Name, volumeName, created)
	b.emit.Normalf(
		events.ReasonVolumesEnsured,
		"ensured VAST volume %q for PVC %s/%s", volumeName, sourcePVC.Namespace, sourcePVC.Name,
	)

	return nil
}

// deleteVastVolumeByName deletes the VAST block volume named volumeName on the
// cluster reached via rest.  The volume ID is resolved via the cached
// VolumeMapping for sc; returns nil if the volume is already absent.
func (b *BlockProvisioner) deleteVastVolumeByName(ctx context.Context, rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, volumeName string) error {
	vol, err := b.getVolume(ctx, sc, volumeName)
	if err != nil {
		return err
	}
	if vol == nil {
		b.logger.Info(fmt.Sprintf("Volume %s is already deleted", volumeName))
		return nil
	}
	if err := vast_client.IgnoreStatusCodes(rest.Volumes.DeleteById(vol.Id, true), 404); err != nil {
		return fmt.Errorf("delete VAST volume %s: %w", volumeName, err)
	}
	return nil
}

// deleteBlockVastVolume deletes the VAST block volume that backs the mirrored
// destination PVC for sourcePVCName on this VRC's own cluster reached via rest.
func (b *BlockProvisioner) deleteBlockVastVolume(ctx context.Context, rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, sourcePVCName string) error {
	pvcs, err := b.k8sClient.ListPVCsByLabelSelector(ctx, b.rp.Namespace, map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelSourcePVC:    sourcePVCName,
		common.LabelStorageClass: sc.Name,
	})
	if err != nil {
		return err
	}
	var errs cerrors.DeferredError
	for i := range pvcs {
		pv, pvErr := b.managedPVForPVC(ctx, &pvcs[i])
		if pvErr != nil {
			errs.Add(pvErr)
			continue
		}
		if pv == nil || pv.Spec.CSI == nil || pv.Spec.CSI.VolumeHandle == "" {
			continue
		}
		volumeName := b.BackendObjectKey(pv.Spec.CSI.VolumeHandle)
		if err := b.deleteVastVolumeByName(ctx, rest, sc, volumeName); err != nil {
			errs.Add(err)
		}
	}
	return errs.Err()
}
