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

	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/util/retry"
	"sigs.k8s.io/controller-runtime/pkg/client"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

// GetVastVolumeReplication retrieves a VastVolumeReplication by name and namespace.
func (k *K8sClient) GetVastVolumeReplication(ctx context.Context, name, namespace string) (*vastv1alpha1.VastVolumeReplication, error) {
	obj := &vastv1alpha1.VastVolumeReplication{}
	if err := k.GetObject(ctx, name, namespace, obj); err != nil {
		return nil, wrapGetError("VastVolumeReplication", name, namespace, err)
	}
	return obj, nil
}

// UpdateVastVolumeReplication persists spec changes to a VastVolumeReplication object,
// retrying on optimistic-concurrency conflicts by refreshing the ResourceVersion
// while keeping all in-memory spec mutations intact.
func (k *K8sClient) UpdateVastVolumeReplication(ctx context.Context, vvr *vastv1alpha1.VastVolumeReplication) error {
	if err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		err := k.UpdateObject(ctx, vvr)
		if k8serrors.IsConflict(err) {
			if refreshErr := k.refreshObjectMetadata(ctx, vvr); refreshErr != nil {
				return refreshErr
			}
		}
		return err
	}); err != nil {
		return fmt.Errorf("failed to update VastVolumeReplication %s/%s: %w", vvr.Namespace, vvr.Name, err)
	}
	return nil
}

// UpdateVastVolumeReplicationStatus persists the full status sub-resource,
// retrying on optimistic-concurrency conflicts.
func (k *K8sClient) UpdateVastVolumeReplicationStatus(ctx context.Context, vvr *vastv1alpha1.VastVolumeReplication) error {
	if err := k.UpdateStatusWithRetry(ctx, vvr); err != nil {
		return fmt.Errorf("failed to update VastVolumeReplication status %s/%s: %w", vvr.Namespace, vvr.Name, err)
	}
	return nil
}

// DeleteVastVolumeReplication issues a delete request for a VastVolumeReplication.
// The controller's finalizer keeps the object alive until all owned resources
// have been cleaned up.
func (k *K8sClient) DeleteVastVolumeReplication(ctx context.Context, vvr *vastv1alpha1.VastVolumeReplication) error {
	if err := k.client.Delete(ctx, vvr); err != nil && !k8serrors.IsNotFound(err) {
		return fmt.Errorf("failed to delete VastVolumeReplication %s/%s: %w", vvr.Namespace, vvr.Name, err)
	}
	return nil
}

// ListVastVolumeReplications lists all VastVolumeReplication objects.
// Pass namespace="" to list across all namespaces.
func (k *K8sClient) ListVastVolumeReplications(ctx context.Context, namespace string) ([]vastv1alpha1.VastVolumeReplication, error) {
	list := &vastv1alpha1.VastVolumeReplicationList{}
	opts := []client.ListOption{}
	if namespace != "" {
		opts = append(opts, client.InNamespace(namespace))
	}
	if err := k.client.List(ctx, list, opts...); err != nil {
		return nil, fmt.Errorf("failed to list VastVolumeReplications: %w", err)
	}
	return list.Items, nil
}
