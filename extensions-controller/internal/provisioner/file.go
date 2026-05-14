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

// FileProvisioner creates Views and Quotas on the VAST cluster.
type FileProvisioner struct {
	*baseProvisioner

	viewCaches       lazyCacheMap[map[string]any]
	quotaCaches      lazyCacheMap[map[string]any]
	viewPolicyCaches lazyCacheMap[*typed.ViewPolicyDetailsModel]
}

// NewFileProvisioner creates a new FileProvisioner for the given ReplicationProvision.
func NewFileProvisioner(ctx context.Context, rp *vastv1alpha1.VastReplicationContent, k8sClient *k8s_client.K8sClient, emit *events.BoundReporter, cfg *config.Config) (*FileProvisioner, error) {
	base, err := newBase(ctx, rp, k8sClient, emit, cfg)
	if err != nil {
		return nil, err
	}
	p := &FileProvisioner{baseProvisioner: base}
	base.setProvisioner(p)
	return p, nil
}

// VolumeMapping implements VolumeMapper.  Returns a map of path →
// *typed.ViewDetailsModel (stored as any) for all VAST NFS views under the
// given StorageClass's root export.  Results are cached per StorageClass name.
func (f *FileProvisioner) VolumeMapping(ctx context.Context, sc *storagev1.StorageClass) (map[string]any, error) {
	return f.viewCaches.get(sc.Name, func() (map[string]any, error) {
		rest, err := vmsrest.NewFromStorageClass(ctx, f.k8sClient, sc, f.config.SSLVerify, f.logger)
		if err != nil {
			return nil, err
		}
		srcParams := f.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, f.sourceSc.Parameters)
		rootExport := srcParams[common.StorageClassParameterRootExport]

		views, err := rest.Views.List(&typed.ViewSearchParams{
			RawData: vast_client.Params{
				"path__startswith": rootExport,
				"fields":           "id,path,tenant_id",
			},
		})
		if err != nil {
			return nil, fmt.Errorf("failed to list views under %s: %w", rootExport, err)
		}
		m := make(map[string]any, len(views))
		for _, v := range views {
			m[strings.TrimRight(v.Path, "/")] = v
		}
		return m, nil
	})
}

// getView returns the cached *typed.ViewDetailsModel for the full view path
// targetPath (e.g. "/k8s/pvc-123"), or nil if absent.
func (f *FileProvisioner) getView(ctx context.Context, sc *storagev1.StorageClass, targetPath string) (*typed.ViewDetailsModel, error) {
	mapping, err := f.VolumeMapping(ctx, sc)
	if err != nil {
		return nil, err
	}
	v, ok := mapping[strings.TrimRight(targetPath, "/")]
	if !ok {
		return nil, nil
	}
	return v.(*typed.ViewDetailsModel), nil
}

// getQuota returns the cached *typed.QuotaDetailsModel for the full path
// targetPath (e.g. "/k8s/pvc-123"), or nil if absent.
func (f *FileProvisioner) getQuota(rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, targetPath string) (*typed.QuotaDetailsModel, error) {
	m, err := f.quotaCaches.get(sc.Name, func() (map[string]any, error) {
		srcParams := f.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, f.sourceSc.Parameters)
		rootExport := srcParams[common.StorageClassParameterRootExport]
		quotas, err := rest.Quotas.List(&typed.QuotaSearchParams{
			RawData: vast_client.Params{
				"path__startswith": rootExport,
				"fields":           "id,path",
			},
		})
		if err != nil {
			return nil, fmt.Errorf("failed to list quotas under %s: %w", rootExport, err)
		}
		m := make(map[string]any, len(quotas))
		for _, q := range quotas {
			m[strings.TrimRight(q.Path, "/")] = q
		}
		return m, nil
	})
	if err != nil {
		return nil, err
	}
	v, ok := m[strings.TrimRight(targetPath, "/")]
	if !ok {
		return nil, nil
	}
	return v.(*typed.QuotaDetailsModel), nil
}

// getViewPolicy returns the *typed.ViewPolicyDetailsModel for policyName on sc.
func (f *FileProvisioner) getViewPolicy(rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, policyName string) (*typed.ViewPolicyDetailsModel, error) {
	return f.viewPolicyCaches.get(sc.Name, func() (*typed.ViewPolicyDetailsModel, error) {
		policy, err := rest.ViewPolicies.Get(&typed.ViewPolicySearchParams{Name: policyName})
		if err != nil {
			return nil, fmt.Errorf("failed to get view policy %q: %w", policyName, err)
		}
		return policy, nil
	})
}

func (f *FileProvisioner) ShouldGateMirrorOnBackend() bool { return true }

// BackendObjectKey implements VolumeMapper.  Returns the full view path used
// as a key in VolumeMapping
func (f *FileProvisioner) BackendObjectKey(volumeHandle string) string {
	if strings.HasPrefix(volumeHandle, "/") {
		return volumeHandle
	}
	srcParams := f.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, f.sourceSc.Parameters)
	rootExport := srcParams[common.StorageClassParameterRootExport]
	return strings.TrimRight(path.Join(rootExport, path.Base(volumeHandle)), "/")
}

// ---------------------------------------------------------------------------
// ProvisionStep: syncVastObjects
// ---------------------------------------------------------------------------

// ProvisionVolumeCb implements Interface.  Called by ProvisionVolumes for this VRC's own cluster.
// Ensures VAST NFS views and quotas exist on this VRC's own cluster and removes
// them for PVCs no longer in the source list.
func (f *FileProvisioner) ProvisionVolumeCb(ctx context.Context, _ *vastv1alpha1.VastReplicationContent, sibRest *vast_client.TypedVMSRest, sibSc *storagev1.StorageClass) error {
	ppath, err := f.getPPath(ctx, sibSc)
	if err != nil {
		return err
	}
	if isDestinationRole(ppath.Role) {
		return nil
	}
	return f.syncFileObjects(ctx, sibRest, sibSc, f.toEnsure, f.toDelete)
}

// CleanVolumeCb implements Interface.  Deletes VAST NFS views and quotas for
// all managed mirror PVCs on this VRC's own cluster.
func (f *FileProvisioner) CleanVolumeCb(ctx context.Context, _ *vastv1alpha1.VastReplicationContent, sibRest *vast_client.TypedVMSRest, sibSc *storagev1.StorageClass) error {
	if !f.rp.Spec.SyncVastObjects {
		return nil
	}
	if f.rp.Spec.DestVolReclaimPolicy == vastv1alpha1.DestVolReclaimPolicyRetain {
		return nil
	}
	pvcs, err := f.k8sClient.ListPVCsByLabelSelector(ctx, f.rp.Namespace, map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelStorageClass: sibSc.Name,
	})
	if err != nil {
		return fmt.Errorf("list managed mirror PVCs for %s: %w", sibSc.Name, err)
	}
	var errs cerrors.DeferredError
	for i := range pvcs {
		pvc := &pvcs[i]
		pv, pvErr := f.managedPVForPVC(ctx, pvc)
		if pvErr != nil {
			errs.Add(pvErr)
			continue
		}
		if pv == nil || pv.Spec.CSI == nil || pv.Spec.CSI.VolumeHandle == "" {
			continue
		}
		viewPath := f.BackendObjectKey(pv.Spec.CSI.VolumeHandle)
		var pvcErrs cerrors.DeferredError
		if err := f.deleteVastQuota(ctx, sibRest, sibSc, viewPath); err != nil {
			pvcErrs.Add(fmt.Errorf("delete quota at %s: %w", viewPath, err))
		}
		if err := f.deleteVastView(ctx, sibRest, sibSc, viewPath); err != nil {
			pvcErrs.Add(fmt.Errorf("delete view at %s: %w", viewPath, err))
		}
		if pvcErrs.IsEmpty() {
			f.emit.Normalf(events.ReasonVASTVolumeDeleted, "deleted VAST view+quota at %s for mirror PVC %s", viewPath, pvc.Name)
		} else {
			errs.Merge(&pvcErrs)
		}
	}
	return errs.Err()
}

// syncFileObjects creates or deletes VAST NFS views and quotas on this VRC's
// own cluster.
func (f *FileProvisioner) syncFileObjects(
	ctx context.Context,
	sibRest *vast_client.TypedVMSRest,
	sibSc *storagev1.StorageClass,
	toEnsure []VolumePair, toDelete vastv1alpha1.PVCList,
) error {
	sibParams := f.k8sClient.ExtractNonPrefixedParams(common.CSIParameterPrefix, sibSc.Parameters)
	viewPolicyName := sibParams["view_policy"]
	qosPolicy := sibParams["qos_policy"]
	qosPolicyIdStr := sibParams[common.StorageClassParameterQosPolicyId]

	var errs cerrors.DeferredError

	for _, pair := range toEnsure {
		if err := f.ensureFileVastObject(ctx, sibRest, sibSc, pair, viewPolicyName, qosPolicy, qosPolicyIdStr); err != nil {
			errs.Add(fmt.Errorf("sync view+quota for %s: %w", pair.PVC.Name, err))
		}
	}

	for _, pvcName := range toDelete {
		if err := f.deleteFileVastObject(ctx, sibRest, sibSc, pvcName); err != nil {
			errs.Add(fmt.Errorf("delete view+quota for source %s: %w", pvcName, err))
		}
	}
	return errs.Err()
}

// ensureFileVastObject creates or verifies the VAST View and Quota for a
// single source PVC on this VRC's own cluster reached via rest.
func (f *FileProvisioner) ensureFileVastObject(
	ctx context.Context,
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
	pair VolumePair,
	viewPolicyName, qosPolicy, qosPolicyIdStr string,
) error {
	sourcePVC := pair.PVC
	sourcePV := pair.PV
	rawVolumeName := path.Base(sourcePV.Spec.CSI.VolumeHandle)
	targetPath := f.BackendObjectKey(sourcePV.Spec.CSI.VolumeHandle)

	view, err := f.ensureView(ctx, rest, sc, targetPath, viewPolicyName, qosPolicy, qosPolicyIdStr)
	if err != nil {
		return fmt.Errorf("ensure view at %s: %w", targetPath, err)
	}
	if view == nil {
		return nil // not source role, object absent — skip silently
	}

	if storageRequest, found := sourcePVC.Spec.Resources.Requests[corev1.ResourceStorage]; found {
		if err := f.ensureQuota(rest, sc, targetPath, rawVolumeName, view.TenantId, storageRequest.Value()); err != nil {
			return fmt.Errorf("ensure quota at %s: %w", targetPath, err)
		}
	}
	return nil
}

// ensureView ensures a VAST View exists at targetPath on this VRC's own cluster.
func (f *FileProvisioner) ensureView(
	ctx context.Context,
	rest *vast_client.TypedVMSRest,
	sc *storagev1.StorageClass,
	targetPath, viewPolicyName, qosPolicy, qosPolicyIdStr string,
) (*typed.ViewUpsertModel, error) {
	if cached, err := f.getView(ctx, sc, targetPath); err != nil {
		return nil, err
	} else if cached != nil {
		return cached, nil
	}

	if viewPolicyName == "" {
		return nil, fmt.Errorf("view_policy parameter not found in StorageClass %s", sc.Name)
	}

	viewPolicy, err := f.getViewPolicy(rest, sc, viewPolicyName)
	if err != nil {
		return nil, err
	}

	protocols := nfsProtocols(sc.MountOptions)
	viewBody := &typed.ViewRequestBody{
		Path:      targetPath,
		PolicyId:  viewPolicy.Id,
		Protocols: &protocols,
		CreateDir: true,
	}
	if qosPolicy != "" {
		viewBody.QosPolicy = qosPolicy
	}
	if qosPolicyIdStr != "" {
		id, err := strconv.ParseInt(qosPolicyIdStr, 10, 64)
		if err != nil {
			return nil, fmt.Errorf("invalid qos_policy_id %q: %w", qosPolicyIdStr, err)
		}
		viewBody.QosPolicyId = id
	}
	view, err := rest.Views.Create(viewBody)
	if err != nil {
		return nil, fmt.Errorf("failed to create view %s: %w", targetPath, err)
	}
	f.viewCaches.add(sc.Name, targetPath, view)
	f.emit.Normalf(events.ReasonViewCreated, "created view %s on own cluster (StorageClass %s)", targetPath, sc.Name)
	return view, nil
}

// ensureQuota ensures a VAST Quota exists at targetPath.
func (f *FileProvisioner) ensureQuota(rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, targetPath, quotaName string, tenantId, hardLimit int64) error {
	if cached, err := f.getQuota(rest, sc, targetPath); err != nil {
		return err
	} else if cached != nil {
		return nil
	}

	created, err := rest.Quotas.Create(&typed.QuotaRequestBody{
		Name:      quotaName,
		Path:      targetPath,
		TenantId:  tenantId,
		HardLimit: hardLimit,
	})
	if err != nil {
		return fmt.Errorf("failed to create quota for view %s: %w", targetPath, err)
	}
	f.quotaCaches.add(sc.Name, targetPath, created)
	f.emit.Normalf(events.ReasonQuotaCreated, "created quota %s (hardLimit=%d) on own cluster", targetPath, hardLimit)
	return nil
}

// deleteFileVastObject deletes the VAST view and quota that back the mirrored
// destination PVC for sourcePVCName on this VRC's own cluster reached via rest.
func (f *FileProvisioner) deleteFileVastObject(ctx context.Context, rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, sourcePVCName string) error {
	pvcs, err := f.k8sClient.ListPVCsByLabelSelector(ctx, f.rp.Namespace, map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelSourcePVC:    sourcePVCName,
		common.LabelStorageClass: sc.Name,
	})
	if err != nil {
		return err
	}
	var errs cerrors.DeferredError
	for i := range pvcs {
		pv, pvErr := f.managedPVForPVC(ctx, &pvcs[i])
		if pvErr != nil {
			return pvErr
		}
		if pv == nil || pv.Spec.CSI == nil || pv.Spec.CSI.VolumeHandle == "" {
			continue
		}
		viewPath := pv.Spec.CSI.VolumeHandle
		if err := f.deleteVastQuota(ctx, rest, sc, viewPath); err != nil {
			errs.Add(err)
		}
		if err := f.deleteVastView(ctx, rest, sc, viewPath); err != nil {
			errs.Add(err)
		}
	}
	if errs.IsEmpty() {
		f.emit.Normalf(events.ReasonVASTVolumeDeleted, "deleted VAST view and quota for source PVC %s (StorageClass %s)", sourcePVCName, sc.Name)
	}
	return errs.Err()
}

// deleteVastQuota deletes the VAST Quota at viewPath on this VRC's own cluster.
// Skips the REST call when the quota is not present in the cache (already absent).
func (f *FileProvisioner) deleteVastQuota(_ context.Context, rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, viewPath string) error {
	quota, err := f.getQuota(rest, sc, viewPath)
	if err != nil {
		return err
	}
	if quota == nil {
		f.logger.Info(fmt.Sprintf("Volume %s is already deleted", viewPath))
		return nil
	}
	if err := vast_client.IgnoreStatusCodes(
		rest.Quotas.DeleteById(quota.Id), 404,
	); err != nil {
		return fmt.Errorf("delete VAST quota at %s: %w", viewPath, err)
	}
	return nil
}

// deleteVastView deletes the VAST NFS View at viewPath on this VRC's own cluster.
// Skips the REST call when the view is not present in the cache (already absent).
func (f *FileProvisioner) deleteVastView(ctx context.Context, rest *vast_client.TypedVMSRest, sc *storagev1.StorageClass, viewPath string) error {
	view, err := f.getView(ctx, sc, viewPath)
	if err != nil {
		return err
	}
	if view == nil {
		f.logger.Info(fmt.Sprintf("View %s is already deleted", viewPath))
		return nil
	}
	if err := vast_client.IgnoreStatusCodes(
		rest.Views.DeleteById(view.Id, false), 404,
	); err != nil {
		return fmt.Errorf("delete VAST view %s: %w", viewPath, err)
	}
	return nil
}
