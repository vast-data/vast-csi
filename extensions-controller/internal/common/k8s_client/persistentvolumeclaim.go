/*
Copyright 2025.

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

package k8s_client

import (
	"context"
	"fmt"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// GetPVC retrieves a PersistentVolumeClaim by name and namespace.
func (k *K8sClient) GetPVC(ctx context.Context, name, namespace string) (*corev1.PersistentVolumeClaim, error) {
	pvc := &corev1.PersistentVolumeClaim{}
	if err := k.GetObject(ctx, name, namespace, pvc); err != nil {
		if apierrors.IsNotFound(err) {
			k.logger.Debug("PVC not found",
				zap.String("namespace", namespace),
				zap.String("name", name))
		} else {
			k.logger.Error("unexpected error getting PVC", zap.Error(err),
				zap.String("namespace", namespace),
				zap.String("name", name))
		}
		return nil, err
	}
	return pvc, nil
}

// GetPVCandPV retrieves both a PersistentVolumeClaim and its associated
// PersistentVolume.  The third return value bound is false when the PVC exists
// but has not yet been bound to a PV (pv will be nil in that case).  Callers
// should requeue rather than treat an unbound PVC as a fatal error.
func (k *K8sClient) GetPVCandPV(ctx context.Context, pvcName, namespace string) (*corev1.PersistentVolumeClaim, *corev1.PersistentVolume, bool, error) {
	pvc, err := k.GetPVC(ctx, pvcName, namespace)
	if err != nil {
		return nil, nil, false, err
	}

	pv, err := k.GetPVFromPVC(ctx, pvc)
	if err != nil {
		return pvc, nil, false, err
	}
	if pv == nil {
		return pvc, nil, false, nil
	}

	return pvc, pv, true, nil
}

// ListPVCsByLabelSelector lists all PVCs in a namespace that match the given label selector.
func (k *K8sClient) ListPVCsByLabelSelector(ctx context.Context, namespace string, selector map[string]string) ([]corev1.PersistentVolumeClaim, error) {
	pvcList := &corev1.PersistentVolumeClaimList{}
	opts := []client.ListOption{
		client.InNamespace(namespace),
		client.MatchingLabels(selector),
	}
	if err := k.client.List(ctx, pvcList, opts...); err != nil {
		return nil, err
	}
	return pvcList.Items, nil
}

// ListAllPVCs returns every PersistentVolumeClaim in the cluster, across all
// namespaces.  Used by the PVC label backfill logic which must inspect PVCs
// that live outside the controller's own namespace.
func (k *K8sClient) ListAllPVCs(ctx context.Context) ([]corev1.PersistentVolumeClaim, error) {
	list := &corev1.PersistentVolumeClaimList{}
	if err := k.client.List(ctx, list); err != nil {
		return nil, fmt.Errorf("failed to list PVCs cluster-wide: %w", err)
	}
	return list.Items, nil
}

// PatchPVCLabels persists the in-memory label map of pvc back to the API
// server using a strategic-merge patch, retrying on optimistic-lock conflicts.
func (k *K8sClient) PatchPVCLabels(ctx context.Context, pvc *corev1.PersistentVolumeClaim) error {
	desiredLabels := pvc.GetLabels()
	if err := k.PatchWithRetry(ctx, pvc, func() {
		pvc.SetLabels(desiredLabels)
	}); err != nil {
		return fmt.Errorf("failed to patch labels on PVC %s/%s: %w", pvc.Namespace, pvc.Name, err)
	}
	return nil
}

// ApplyExistingPVCs injects the storageClass label (and subsystem label for
// block StorageClasses) onto all existing PVCs whose backing VAST object
// appears in the VolumeMapping for scName.
//
// A PVC is considered owned by scName when the Kubernetes PV it is bound to
// has a name that is a suffix of any VolumeMapping key.  For example:
//
//   - Block key "group/pvc-abc123" ends with PV name "pvc-abc123" → match.
//   - File key "/k8s/pvc-abc123"  ends with PV name "pvc-abc123" → match.
//
// PVCs that already carry both labels are skipped.  Per-PVC patch errors are
// logged but do not abort the backfill of remaining PVCs.
func (k *K8sClient) ApplyExistingPVCs(
	ctx context.Context,
	scName string,
	sc *storagev1.StorageClass,
	rest *vast_client.TypedVMSRest,
	log *zap.Logger,
) error {
	mapping, err := k.backfillVolumeMapping(ctx, sc, rest)
	if err != nil {
		return fmt.Errorf("list backend objects for %s: %w", scName, err)
	}
	if len(mapping) == 0 {
		log.Info("no backend objects found for StorageClass; skipping PVC label backfill",
			zap.String("sc", scName))
		return nil
	}

	pvcs, err := k.ListAllPVCs(ctx)
	if err != nil {
		return fmt.Errorf("list PVCs: %w", err)
	}

	subsystem := sc.Parameters[common.StorageClassParameterSubsystem]
	isBlock := IsBlockStorageClass(sc)

	patched := 0
	for i := range pvcs {
		pvc := &pvcs[i]

		if pvc.Spec.StorageClassName == nil || *pvc.Spec.StorageClassName != scName {
			continue
		}

		pvName := pvc.Spec.VolumeName
		if !backfillMappingContainsPV(mapping, pvName) {
			continue
		}

		needsSCLabel := !k.HasLabel(pvc, common.LabelStorageClass)
		needsSubsystemLabel := isBlock && subsystem != "" && !k.HasLabel(pvc, common.LabelSubsystem)

		if !needsSCLabel && !needsSubsystemLabel {
			continue
		}

		if needsSCLabel {
			k.SetLabel(pvc, common.LabelStorageClass, scName)
		}
		if needsSubsystemLabel {
			k.SetLabel(pvc, common.LabelSubsystem, subsystem)
		}

		if err := k.PatchPVCLabels(ctx, pvc); err != nil {
			log.Warn("failed to patch PVC labels during backfill",
				zap.String("pvc", pvc.Namespace+"/"+pvc.Name),
				zap.Error(err))
			continue
		}

		log.Info("backfilled labels on PVC",
			zap.String("pvc", pvc.Namespace+"/"+pvc.Name),
			zap.String("sc", scName),
			zap.String("pv", pvName))
		patched++
	}

	if patched > 0 {
		log.Info("PVC label backfill complete",
			zap.String("sc", scName),
			zap.Int("patched", patched))
	}
	return nil
}

// backfillVolumeMapping fetches the set of VAST backend object keys for sc.
func (k *K8sClient) backfillVolumeMapping(
	ctx context.Context,
	sc *storagev1.StorageClass,
	rest *vast_client.TypedVMSRest,
) (map[string]struct{}, error) {
	params := k.ExtractNonPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
	if IsBlockStorageClass(sc) {
		return backfillBlockMapping(rest, params)
	}
	return backfillFileMapping(rest, params)
}

func backfillBlockMapping(rest *vast_client.TypedVMSRest, params map[string]string) (map[string]struct{}, error) {
	subsystem := params[common.StorageClassParameterSubsystem]
	volumeGroup := strings.TrimPrefix(params[common.StorageClassParameterVolumeGroup], "/")

	searchParams := vast_client.Params{
		"subsystem_name": subsystem,
		"fields":         "name",
	}
	if volumeGroup != "" {
		searchParams["name__contains"] = volumeGroup
	}

	vols, err := rest.Volumes.List(&typed.VolumeSearchParams{
		RawData: searchParams,
	})
	if err != nil {
		return nil, fmt.Errorf("list volumes (subsystem=%s): %w", subsystem, err)
	}

	m := make(map[string]struct{}, len(vols))
	for _, v := range vols {
		m[strings.TrimRight(v.Name, "/")] = struct{}{}
	}
	return m, nil
}

func backfillFileMapping(rest *vast_client.TypedVMSRest, params map[string]string) (map[string]struct{}, error) {
	rootExport := params[common.StorageClassParameterRootExport]

	views, err := rest.Views.List(&typed.ViewSearchParams{
		RawData: vast_client.Params{
			"path__startswith": rootExport,
			"fields":           "path",
		},
	})
	if err != nil {
		return nil, fmt.Errorf("list views (root_export=%s): %w", rootExport, err)
	}

	m := make(map[string]struct{}, len(views))
	for _, v := range views {
		m[strings.TrimRight(v.Path, "/")] = struct{}{}
	}
	return m, nil
}

// backfillMappingContainsPV reports true when any key in mapping ends with pvName.
func backfillMappingContainsPV(mapping map[string]struct{}, pvName string) bool {
	for key := range mapping {
		if strings.HasSuffix(key, pvName) {
			return true
		}
	}
	return false
}

// EnsurePVC ensures a PersistentVolumeClaim exists.
// Returns (true, nil) when the PVC was freshly created, (false, nil) when it
// already existed, and (false, err) on any API error.
func (k *K8sClient) EnsurePVC(ctx context.Context, pvc *corev1.PersistentVolumeClaim) (bool, error) {
	_, err := k.GetPVC(ctx, pvc.Name, pvc.Namespace)
	if err == nil {
		return false, nil
	}
	if !apierrors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing PersistentVolumeClaim %s/%s: %w", pvc.Namespace, pvc.Name, err)
	}
	if err := k.client.Create(ctx, pvc); err != nil {
		if apierrors.IsAlreadyExists(err) {
			k.logger.Info("PersistentVolumeClaim was created by another process",
				zap.String("name", pvc.Name),
				zap.String("namespace", pvc.Namespace))
			return false, nil
		}
		return false, fmt.Errorf("failed to create PersistentVolumeClaim %s/%s: %w", pvc.Namespace, pvc.Name, err)
	}
	return true, nil
}
