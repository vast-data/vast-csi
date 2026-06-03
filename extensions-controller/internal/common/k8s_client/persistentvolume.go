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
	"k8s.io/apimachinery/pkg/api/errors"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

func (k *K8sClient) GetPVFromPVC(ctx context.Context, pvc *corev1.PersistentVolumeClaim) (*corev1.PersistentVolume, error) {
	pvName := k.getPVNameFromPVC(pvc)
	if pvName == "" {
		k.logger.Info("PVC does not have associated PV")
		return nil, nil
	}

	pv, err := k.getPV(ctx, pvName)
	if err != nil {
		if errors.IsNotFound(err) {
			return nil, fmt.Errorf("PV %s does not exist for PVC %s/%s: %w", pvName, pvc.Namespace, pvc.Name, err)
		}
		return nil, err
	}
	return pv, nil
}

func (k *K8sClient) getPVNameFromPVC(pvc *corev1.PersistentVolumeClaim) string {
	return pvc.Spec.VolumeName
}

func (k *K8sClient) getPV(ctx context.Context, pvName string) (*corev1.PersistentVolume, error) {
	return k.GetPV(ctx, pvName)
}

// ListPVsByLabelSelector lists all PVs that match the given label selector.
// PVs are cluster-scoped, so no namespace is required.
func (k *K8sClient) ListPVsByLabelSelector(ctx context.Context, selector map[string]string) ([]corev1.PersistentVolume, error) {
	pvList := &corev1.PersistentVolumeList{}
	opts := []client.ListOption{
		client.MatchingLabels(selector),
	}
	if err := k.client.List(ctx, pvList, opts...); err != nil {
		return nil, err
	}
	return pvList.Items, nil
}

// GetPV retrieves a PersistentVolume by name.
func (k *K8sClient) GetPV(ctx context.Context, name string) (*corev1.PersistentVolume, error) {
	pv := &corev1.PersistentVolume{}
	// PersistentVolume is cluster-scoped, so namespace is empty
	if err := k.GetObject(ctx, name, "", pv); err != nil {
		return nil, err
	}
	return pv, nil
}

// EnsurePV ensures a PersistentVolume exists.
// Returns (true, nil) when the PV was freshly created, (false, nil) when it
// already existed, and (false, err) on any API error.
// PVs are cluster-scoped, so no namespace is required.
func (k *K8sClient) EnsurePV(ctx context.Context, pv *corev1.PersistentVolume) (bool, error) {
	_, err := k.GetPV(ctx, pv.Name)
	if err == nil {
		return false, nil
	}
	if !errors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing PersistentVolume %s: %w", pv.Name, err)
	}

	if err := k.client.Create(ctx, pv); err != nil {
		if errors.IsAlreadyExists(err) {
			k.logger.Info("PersistentVolume was created by another process", zap.String("name", pv.Name))
			return false, nil
		}
		return false, fmt.Errorf("failed to create PersistentVolume %s: %w", pv.Name, err)
	}
	return true, nil
}

// PatchPVLabels persists the in-memory label map of pv back to the API server
// using a merge patch, retrying on optimistic-lock conflicts.
func (k *K8sClient) PatchPVLabels(ctx context.Context, pv *corev1.PersistentVolume) error {
	desiredLabels := pv.GetLabels()
	if err := k.PatchWithRetry(ctx, pv, func() {
		pv.SetLabels(desiredLabels)
	}); err != nil {
		return fmt.Errorf("failed to patch labels on PV %s: %w", pv.Name, err)
	}
	return nil
}
