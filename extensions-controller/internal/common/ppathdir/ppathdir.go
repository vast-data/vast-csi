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

// Package ppathdir provides helpers for predicting the ppath SourceDir of a
// VAST protected path from a StorageClass configuration and optional REST
// queries against the VAST cluster.
package ppathdir

import (
	"context"
	"fmt"
	"path"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/go-vast-client/resources/typed/expr"
	"go.uber.org/zap"
	storagev1 "k8s.io/api/storage/v1"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
)

// Predict returns the predicted ppath SourceDir for the given primary
// StorageClass.  The result is required: a non-empty PpathDir must be present
// in status before the reconcile is considered successful.
//
// For VSCR (volumeName == ""):
//   - Block StorageClass: fetches the subsystem View from the VAST REST API
//     and returns path.Join(subsystem.Path, volume_group).
//   - File StorageClass: returns the root_export parameter directly (no REST
//     call required).
//
// For VVR (volumeName != "", namespace != ""):
//   - The PVC named volumeName is fetched from the cluster to obtain its bound
//     PV and the CSI volume handle (e.g. "pvc-8322d00f-...").  That handle is
//     the name VAST uses for the view / volume, not the PVC name.
//   - Block StorageClass: queries Volumes by name__contains=volumeHandle,
//     looks up the View (subsystem) by the volume's ViewId, and returns
//     path.Join(subsystem.Path, volume.Name).
//   - File StorageClass: queries Views by path__contains=volumeHandle and
//     returns the matching view's Path.
func Predict(
	ctx context.Context,
	k8sClient *k8sclient.K8sClient,
	sc *storagev1.StorageClass,
	sslVerify bool,
	log *zap.Logger,
	volumeName string,
	namespace string,
) (string, error) {
	nonPrefixedParams := k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
	isBlock := k8sclient.IsBlockStorageClass(sc)

	if volumeName == "" {
		return predictSCR(ctx, k8sClient, sc, nonPrefixedParams, isBlock, sslVerify, log)
	}
	return predictVVR(ctx, k8sClient, sc, nonPrefixedParams, isBlock, sslVerify, log, volumeName, namespace)
}

// IsSubsystemLevel reports whether sc is a block StorageClass configured for
// subsystem-level replication — i.e. it has a subsystem parameter but no
// volume_group parameter.
//
// In subsystem-level replication the entire VAST subsystem is replicated as a
// unit.  The destination subsystem is created by VAST replication itself, so
// it must NOT be pre-created on secondary clusters.  The ppath source_dir is
// the subsystem's root path, which VAST preserves on the destination cluster,
// so all StorageClasses in the constellation share the primary SC's path.
func IsSubsystemLevel(k8sClient *k8sclient.K8sClient, sc *storagev1.StorageClass) bool {
	if !k8sclient.IsBlockStorageClass(sc) {
		return false
	}
	params := k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
	return strings.TrimPrefix(params[common.StorageClassParameterVolumeGroup], "/") == ""
}

// predictSCR computes PpathDir for a VastStorageClassReplication using the
// primary StorageClass parameters.
func predictSCR(
	ctx context.Context,
	k8sClient *k8sclient.K8sClient,
	sc *storagev1.StorageClass,
	nonPrefixedParams map[string]string,
	isBlock bool,
	sslVerify bool,
	log *zap.Logger,
) (string, error) {
	if !isBlock {
		rootExport := nonPrefixedParams[common.StorageClassParameterRootExport]
		if rootExport == "" {
			return "", fmt.Errorf("StorageClass %s is missing %q parameter", sc.Name, common.StorageClassParameterRootExport)
		}
		return rootExport, nil
	}

	subsystemName := nonPrefixedParams[common.StorageClassParameterSubsystem]
	volumeGroup := strings.TrimPrefix(nonPrefixedParams[common.StorageClassParameterVolumeGroup], "/")

	rest, err := vmsrest.NewFromStorageClass(ctx, k8sClient, sc, sslVerify, log)
	if err != nil {
		return "", fmt.Errorf("failed to build REST client from StorageClass %s: %w", sc.Name, err)
	}

	subsystem, err := rest.Views.Get(&typed.ViewSearchParams{
		Name:    expr.Str(subsystemName),
		RawData: vast_client.Params{"fields": "id,path,tenant_id"},
	})
	if err != nil {
		return "", fmt.Errorf("failed to get subsystem view %q from StorageClass %s: %w", subsystemName, sc.Name, err)
	}

	if volumeGroup == "" {
		// Subsystem-level replication: replicate the entire subsystem.
		// The ppath source_dir is the subsystem root; VAST preserves this path
		// on the destination cluster so no suffix is needed.
		return subsystem.Path, nil
	}
	return path.Join(subsystem.Path, volumeGroup), nil
}

// predictVVR computes PpathDir for a VastVolumeReplication for a single
// StorageClass — which may be the primary or any secondary.
//
// It first resolves the PVC → PV → CSI volume handle from Kubernetes (the
// PVC exists only on the primary cluster, but the k8s API is shared).
//
// For block StorageClasses the subsystem View is fetched from THAT
// StorageClass's cluster (subsystems must pre-exist on every cluster for
// volume-group-level replication), and the predicted path is
// path.Join(subsystem.Path, volumeHandle).
//
// For file StorageClasses the path is derived purely from the SC parameters
// (root_export + volumeHandle), matching exactly how the VAST CSI driver
// names the view when it provisions the PVC.  No REST call is needed because
// the per-SC root_export is the definitive source of truth for the destination
// cluster path.
func predictVVR(
	ctx context.Context,
	k8sClient *k8sclient.K8sClient,
	sc *storagev1.StorageClass,
	nonPrefixedParams map[string]string,
	isBlock bool,
	sslVerify bool,
	log *zap.Logger,
	volumeName string,
	namespace string,
) (string, error) {
	_, pv, bound, err := k8sClient.GetPVCandPV(ctx, volumeName, namespace)
	if err != nil {
		return "", fmt.Errorf("failed to get PV for PVC %s/%s: %w", namespace, volumeName, err)
	}
	if !bound {
		return "", fmt.Errorf("PVC %s/%s not yet bound to a PV", namespace, volumeName)
	}
	if pv.Spec.CSI == nil {
		return "", fmt.Errorf("PV %s has no CSI spec (not a CSI volume?)", pv.Name)
	}
	volumeHandle := pv.Spec.CSI.VolumeHandle
	if volumeHandle == "" {
		return "", fmt.Errorf("PV %s has an empty CSI volume handle", pv.Name)
	}

	if !isBlock {
		return predictFileVVR(sc, nonPrefixedParams, volumeHandle)
	}

	rest, err := vmsrest.NewFromStorageClass(ctx, k8sClient, sc, sslVerify, log)
	if err != nil {
		return "", fmt.Errorf("failed to build REST client from StorageClass %s: %w", sc.Name, err)
	}
	return predictBlockVVR(rest, sc, nonPrefixedParams, volumeHandle)
}

// predictBlockVVR computes the ppath SourceDir for a block StorageClass in a
// VastVolumeReplication.
//
// The logic mirrors predictSCR for block but appends path.Base(volumeHandle)
// at the end to target the specific volume rather than the whole group:
//
//	subsystem.Path [/ volumeGroup] / path.Base(volumeHandle)
//
// Unlike the VSCR path, the volume itself may not yet exist on secondary
// clusters (replication hasn't run yet), so the subsystem View is fetched by
// name from the SC parameters rather than by the volume's ViewId.  VAST
// preserves the volume name during replication, so this path is identical on
// every cluster in the constellation.
func predictBlockVVR(
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
	nonPrefixedParams map[string]string,
	volumeHandle string,
) (string, error) {
	subsystemName := nonPrefixedParams[common.StorageClassParameterSubsystem]
	if subsystemName == "" {
		return "", fmt.Errorf("StorageClass %s is missing required %q parameter", sc.Name, common.StorageClassParameterSubsystem)
	}
	volumeGroup := strings.TrimPrefix(nonPrefixedParams[common.StorageClassParameterVolumeGroup], "/")

	subsystem, err := rest.Views.Get(&typed.ViewSearchParams{
		Name:    expr.Str(subsystemName),
		RawData: vast_client.Params{"fields": "id,path"},
	})
	if err != nil {
		return "", fmt.Errorf("StorageClass %s: failed to get subsystem view %q: %w", sc.Name, subsystemName, err)
	}
	return path.Join(subsystem.Path, volumeGroup, path.Base(volumeHandle)), nil
}

// predictFileVVR computes the ppath SourceDir for a file StorageClass in a
// VastVolumeReplication.
//
// The logic mirrors predictSCR for file but appends path.Base(volumeHandle):
//
//	root_export / path.Base(volumeHandle)
//
// The VAST CSI driver creates one view per PVC at root_export/<volumeHandle>,
// so we reconstruct that path from SC parameters without a REST round-trip.
// This also works for secondary StorageClasses where the view does not yet
// exist (VAST replication will create it with the same relative path under the
// secondary SC's root_export).
func predictFileVVR(
	sc *storagev1.StorageClass,
	nonPrefixedParams map[string]string,
	volumeHandle string,
) (string, error) {
	rootExport := nonPrefixedParams[common.StorageClassParameterRootExport]
	if rootExport == "" {
		return "", fmt.Errorf("StorageClass %s is missing required %q parameter", sc.Name, common.StorageClassParameterRootExport)
	}
	return path.Join(rootExport, path.Base(volumeHandle)), nil
}
