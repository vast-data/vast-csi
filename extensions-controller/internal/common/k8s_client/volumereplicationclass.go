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

package k8s_client

import (
	"context"
	"fmt"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	"go.uber.org/zap"
	"k8s.io/apimachinery/pkg/api/errors"
)

// GetVolumeReplicationClass fetches a VolumeReplicationClass by name and namespace.
func (k *K8sClient) GetVolumeReplicationClass(ctx context.Context, name, namespace string) (*replicationv1alpha1.VolumeReplicationClass, error) {
	vrc := &replicationv1alpha1.VolumeReplicationClass{}
	if err := k.GetObject(ctx, name, namespace, vrc); err != nil {
		if errors.IsNotFound(err) {
			k.logger.Debug("VolumeReplicationClass not found",
				zap.String("name", name),
				zap.String("namespace", namespace))
		} else {
			k.logger.Error("Failed to get VolumeReplicationClass",
				zap.Error(err),
				zap.String("name", name),
				zap.String("namespace", namespace))
		}
		return nil, err
	}
	return vrc, nil
}

// GetVolumeGroupReplicationClass fetches a VolumeGroupReplicationClass by name and namespace.
func (k *K8sClient) GetVolumeGroupReplicationClass(ctx context.Context, name, namespace string) (*replicationv1alpha1.VolumeGroupReplicationClass, error) {
	vgrc := &replicationv1alpha1.VolumeGroupReplicationClass{}
	if err := k.GetObject(ctx, name, namespace, vgrc); err != nil {
		if errors.IsNotFound(err) {
			k.logger.Debug("VolumeGroupReplicationClass not found",
				zap.String("name", name),
				zap.String("namespace", namespace))
		} else {
			k.logger.Error("Failed to get VolumeGroupReplicationClass",
				zap.Error(err),
				zap.String("name", name),
				zap.String("namespace", namespace))
		}
		return nil, err
	}
	return vgrc, nil
}

// ListVolumeReplicationClasses returns every VolumeReplicationClass in the
// cluster regardless of who created it.  Label filtering is intentionally
// avoided so that classes created outside this controller are discoverable.
func (k *K8sClient) ListVolumeReplicationClasses(ctx context.Context) ([]replicationv1alpha1.VolumeReplicationClass, error) {
	list := &replicationv1alpha1.VolumeReplicationClassList{}
	if err := k.client.List(ctx, list); err != nil {
		return nil, fmt.Errorf("failed to list VolumeReplicationClasses: %w", err)
	}
	return list.Items, nil
}

// EnsureVolumeReplicationClass ensures a VolumeReplicationClass exists.
// Since VolumeReplicationClass is immutable, this only creates it if it doesn't exist.
// Returns (true, nil) when freshly created, (false, nil) when it already existed.
func (k *K8sClient) EnsureVolumeReplicationClass(ctx context.Context, vrc *replicationv1alpha1.VolumeReplicationClass) (bool, error) {
	_, err := k.GetVolumeReplicationClass(ctx, vrc.Name, vrc.Namespace)
	if err == nil {
		return false, nil
	}
	if !errors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing VolumeReplicationClass %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}

	if err := k.client.Create(ctx, vrc); err != nil {
		if errors.IsAlreadyExists(err) {
			k.logger.Info("VolumeReplicationClass was created by another process",
				zap.String("name", vrc.Name),
				zap.String("namespace", vrc.Namespace))
			return false, nil
		}
		return false, fmt.Errorf("failed to create VolumeReplicationClass %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}
	return true, nil
}

// EnsureVolumeGroupReplicationClass ensures a VolumeGroupReplicationClass exists.
// Since VolumeGroupReplicationClass is immutable, this only creates it if it doesn't exist.
// Returns (true, nil) when freshly created, (false, nil) when it already existed.
func (k *K8sClient) EnsureVolumeGroupReplicationClass(ctx context.Context, vgrc *replicationv1alpha1.VolumeGroupReplicationClass) (bool, error) {
	_, err := k.GetVolumeGroupReplicationClass(ctx, vgrc.Name, vgrc.Namespace)
	if err == nil {
		return false, nil
	}
	if !errors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing VolumeGroupReplicationClass %s/%s: %w", vgrc.Namespace, vgrc.Name, err)
	}

	if err := k.client.Create(ctx, vgrc); err != nil {
		if errors.IsAlreadyExists(err) {
			k.logger.Info("VolumeGroupReplicationClass was created by another process",
				zap.String("name", vgrc.Name),
				zap.String("namespace", vgrc.Namespace))
			return false, nil
		}
		return false, fmt.Errorf("failed to create VolumeGroupReplicationClass %s/%s: %w", vgrc.Namespace, vgrc.Name, err)
	}
	return true, nil
}
