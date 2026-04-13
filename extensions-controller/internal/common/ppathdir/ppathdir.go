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
	return predictVVR(ctx, k8sClient, sc, isBlock, sslVerify, log, volumeName, namespace)
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
		RawData: vast_client.Params{
			"name":   subsystemName,
			"fields": "id,path,tenant_id",
		},
	})
	if err != nil {
		return "", fmt.Errorf("failed to get subsystem view %q from StorageClass %s: %w", subsystemName, sc.Name, err)
	}

	return path.Join(subsystem.Path, volumeGroup), nil
}

// predictVVR computes PpathDir for a VastVolumeReplication.
//
// It first resolves the PVC → PV → CSI volume handle so that it can query
// the VAST cluster by the handle (e.g. "pvc-8322d00f-...") rather than the
// user-facing PVC name, which VAST never sees.
//
// The PVC must be provisioned by the same StorageClass that is set as
// primaryStorageClass in the VVR spec.
func predictVVR(
	ctx context.Context,
	k8sClient *k8sclient.K8sClient,
	sc *storagev1.StorageClass,
	isBlock bool,
	sslVerify bool,
	log *zap.Logger,
	volumeName string,
	namespace string,
) (string, error) {
	// Resolve PVC → PV → CSI volume handle.
	pvc, pv, bound, err := k8sClient.GetPVCandPV(ctx, volumeName, namespace)
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

	// The PVC must be provisioned by the primaryStorageClass: that is the only
	// cluster where the volume handle exists and can be queried via REST.
	if pvc.Spec.StorageClassName != nil && *pvc.Spec.StorageClassName != sc.Name {
		return "", fmt.Errorf(
			"PVC %s/%s was provisioned by StorageClass %q but primaryStorageClass is %q; "+
				"the PVC must be created with the primary StorageClass",
			namespace, volumeName, *pvc.Spec.StorageClassName, sc.Name,
		)
	}

	rest, err := vmsrest.NewFromStorageClass(ctx, k8sClient, sc, sslVerify, log)
	if err != nil {
		return "", fmt.Errorf("failed to build REST client from StorageClass %s: %w", sc.Name, err)
	}

	if isBlock {
		return predictBlockVVR(rest, volumeHandle)
	}
	return predictFileVVR(rest, volumeHandle)
}

// predictBlockVVR queries Volumes by name__contains=volumeHandle, resolves the
// subsystem View via the volume's ViewId, and returns
// path.Join(subsystem.Path, volume.Name).
func predictBlockVVR(rest *vast_client.TypedVMSRest, volumeHandle string) (string, error) {
	volume, err := rest.Volumes.Get(&typed.VolumeSearchParams{
		RawData: vast_client.Params{
			"name__contains": volumeHandle,
			"fields":         "id,name,view_id",
		},
	})
	if err != nil {
		return "", fmt.Errorf("failed to list volumes containing %q: %w", volumeHandle, err)
	}
	subsystem, err := rest.Views.GetById(volume.ViewId)
	if err != nil {
		return "", fmt.Errorf("failed to get subsystem view (id=%d) for volume %q: %w", volume.ViewId, volume.Name, err)
	}

	return path.Join(subsystem.Path, volume.Name), nil
}

// predictFileVVR queries Views by path__contains=volumeHandle and returns the
// matching view's Path.
func predictFileVVR(rest *vast_client.TypedVMSRest, volumeHandle string) (string, error) {
	view, err := rest.Views.Get(&typed.ViewSearchParams{
		RawData: vast_client.Params{
			"path__contains": volumeHandle,
			"fields":         "id,path,tenant_id",
		},
	})
	if err != nil {
		return "", fmt.Errorf("failed to list views containing %q: %w", volumeHandle, err)
	}

	return view.Path, nil
}
