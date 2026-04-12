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

// GetVastStorageClassReplication retrieves a VastStorageClassReplication by name and namespace.
func (k *K8sClient) GetVastStorageClassReplication(ctx context.Context, name, namespace string) (*vastv1alpha1.VastStorageClassReplication, error) {
	obj := &vastv1alpha1.VastStorageClassReplication{}
	if err := k.GetObject(ctx, name, namespace, obj); err != nil {
		return nil, wrapGetError("VastStorageClassReplication", name, namespace, err)
	}
	return obj, nil
}

// UpdateVastStorageClassReplication persists spec changes to a
// VastStorageClassReplication object, retrying on optimistic-concurrency
// conflicts by refreshing the ResourceVersion while keeping all in-memory
// spec mutations intact.
func (k *K8sClient) UpdateVastStorageClassReplication(ctx context.Context, vscr *vastv1alpha1.VastStorageClassReplication) error {
	if err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		err := k.UpdateObject(ctx, vscr)
		if k8serrors.IsConflict(err) {
			if refreshErr := k.refreshObjectMetadata(ctx, vscr); refreshErr != nil {
				return refreshErr
			}
		}
		return err
	}); err != nil {
		return fmt.Errorf("failed to update VastStorageClassReplication %s/%s: %w", vscr.Namespace, vscr.Name, err)
	}
	return nil
}

// UpdateVastStorageClassReplicationStatus persists the full status sub-resource,
// retrying on optimistic-concurrency conflicts.
func (k *K8sClient) UpdateVastStorageClassReplicationStatus(ctx context.Context, vscr *vastv1alpha1.VastStorageClassReplication) error {
	if err := k.UpdateStatusWithRetry(ctx, vscr); err != nil {
		return fmt.Errorf("failed to update VastStorageClassReplication status %s/%s: %w", vscr.Namespace, vscr.Name, err)
	}
	return nil
}

// ListVastStorageClassReplications lists all VastStorageClassReplication objects.
// Pass namespace="" to list across all namespaces.
func (k *K8sClient) ListVastStorageClassReplications(ctx context.Context, namespace string) ([]vastv1alpha1.VastStorageClassReplication, error) {
	list := &vastv1alpha1.VastStorageClassReplicationList{}
	opts := []client.ListOption{}
	if namespace != "" {
		opts = append(opts, client.InNamespace(namespace))
	}
	if err := k.client.List(ctx, list, opts...); err != nil {
		return nil, err
	}
	return list.Items, nil
}

// DeleteVastStorageClassReplication issues a delete request for a
// VastStorageClassReplication. The controller's finalizer keeps the object
// alive until all owned resources have been cleaned up.
func (k *K8sClient) DeleteVastStorageClassReplication(ctx context.Context, vscr *vastv1alpha1.VastStorageClassReplication) error {
	if err := k.client.Delete(ctx, vscr); err != nil && !k8serrors.IsNotFound(err) {
		return fmt.Errorf("failed to delete VastStorageClassReplication %s/%s: %w", vscr.Namespace, vscr.Name, err)
	}
	return nil
}
