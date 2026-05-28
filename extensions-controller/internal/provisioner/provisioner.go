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

	vast_client "github.com/vast-data/go-vast-client"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/events"
	k8s_client "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	storagev1 "k8s.io/api/storage/v1"
)

// Interface is the common interface for creating VAST storage resources
// based on the CSI driver type (File or Block).
//
// File provisioning creates a View + Quota on the VAST cluster.
// Block provisioning creates a block Volume on the VAST cluster.
//
// Only the PRIMARY VRC drives provisioning; secondary VRCs are no-ops.
// See ProvisionVolumes for the full failover-aware logic.
type Interface interface {
	// ProvisionVolumes syncs all replication resources for this reconcile.
	//
	// The PVC list is computed internally by querying all constellation VRCs
	// and filtering out controller-managed (mirror) PVCs.
	//
	// Primary VRC: syncs VAST objects on own cluster and creates managed
	// PVC+PV pairs on own cluster for every non-managed PVC found across all
	// constellation VRCs.  Before failover only the primary's own cluster has
	// non-managed PVCs.  After failover the old primary's VRC carries the
	// source PVCs and the new primary mirrors them onto itself.
	//
	// Secondary VRC: exits immediately (no-op).
	ProvisionVolumes(ctx context.Context) error

	// ProvisionVolumeCb performs the VAST-object sync for this VRC's own cluster.
	ProvisionVolumeCb(context.Context, *vastv1alpha1.VastReplicationContent, *vast_client.TypedVMSRest, *storagev1.StorageClass) error

	// CleanVolumes removes all resources owned by this VRC on its own cluster.
	CleanVolumes(ctx context.Context) error

	// CleanVolumeCb performs VAST-object cleanup for this VRC's own cluster.
	CleanVolumeCb(context.Context, *vastv1alpha1.VastReplicationContent, *vast_client.TypedVMSRest, *storagev1.StorageClass) error

}

// VolumeMapper provides lazy, cached access to the set of VAST volumes
// managed by a provisioner.
//
// The concrete value type sto	red in the map depends on the provisioner kind:
//   - Block: *typed.VolumeDetailsModel — keyed by full volume name (e.g. "group/pvc-123")
//   - File:  *typed.ViewDetailsModel  — keyed by full view path (e.g. "/k8s/pvc-123")
//
// Keys are normalised by trimming trailing slashes; leading slashes are
// preserved for view paths.  Callers that need the concrete type should
// perform a type assertion on the map values.
type VolumeMapper interface {
	// VolumeMapping returns a map of full volume-name/path → VAST resource
	// object for the given StorageClass.  Results are cached per StorageClass
	// name so each SC pays at most one REST round-trip per provisioner lifetime.
	VolumeMapping(ctx context.Context, sc *storagev1.StorageClass) (map[string]any, error)

	// VolumeIDs returns the sorted list of keys from VolumeMapping for the
	// given StorageClass (full volume names / view paths).
	VolumeIDs(ctx context.Context, sc *storagev1.StorageClass) ([]string, error)

	// BackendObjectKey resolves a CSI volumeHandle to the full VAST object name
	// (view path for file provisioning, volume name for block provisioning).
	BackendObjectKey(volumeHandle string) string

	// VolumeCount returns the number of backend objects present for the given
	// StorageClass (equivalent to len(VolumeIDs)).
	VolumeCount(ctx context.Context, sc *storagev1.StorageClass) (int, error)
}

// NewProvisioner creates an Interface for provisioning from a VastReplicationContent object.
// Dispatches on ProvisionerType (Block or File).
func NewProvisioner(
	ctx context.Context,
	k8sClient *k8s_client.K8sClient,
	rp *vastv1alpha1.VastReplicationContent,
	emit *events.BoundReporter,
	cfg *config.Config,
) (Interface, error) {
	switch rp.Spec.ProvisionerType {
	case vastv1alpha1.ProvisionerTypeBlock:
		return NewBlockProvisioner(ctx, rp, k8sClient, emit, cfg)
	case vastv1alpha1.ProvisionerTypeFile:
		return NewFileProvisioner(ctx, rp, k8sClient, emit, cfg)
	default:
		return nil, fmt.Errorf("unknown ProvisionerType %q in VastReplicationContent %s/%s",
			rp.Spec.ProvisionerType, rp.Namespace, rp.Name)
	}
}
