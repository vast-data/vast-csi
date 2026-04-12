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

	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
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
