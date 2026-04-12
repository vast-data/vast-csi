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
	stderrors "errors"
	"fmt"

	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/labels"
	"sigs.k8s.io/controller-runtime/pkg/client"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
)

// ErrVastReplicationContentTerminating is returned when a VRC that the caller
// needs to create or update still has a DeletionTimestamp set.
// The caller must wait for the object to be fully removed before proceeding.
var ErrVastReplicationContentTerminating = stderrors.New("VastReplicationContent is terminating")

// GetVastReplicationContent retrieves a VastReplicationContent by name and namespace.
func (k *K8sClient) GetVastReplicationContent(ctx context.Context, name, namespace string) (*vastv1alpha1.VastReplicationContent, error) {
	vrc := &vastv1alpha1.VastReplicationContent{}
	if err := k.GetObject(ctx, name, namespace, vrc); err != nil {
		return nil, err
	}
	return vrc, nil
}

// ListVastReplicationContentsByLabelSelector lists all VastReplicationContent objects in the
// given namespace that match the provided label selector map.
func (k *K8sClient) ListVastReplicationContentsByLabelSelector(ctx context.Context, namespace string, selector map[string]string) ([]vastv1alpha1.VastReplicationContent, error) {
	list := &vastv1alpha1.VastReplicationContentList{}
	if err := k.client.List(ctx, list,
		client.InNamespace(namespace),
		client.MatchingLabels(selector),
	); err != nil {
		return nil, fmt.Errorf("failed to list VastReplicationContents in %s: %w", namespace, err)
	}
	return list.Items, nil
}

// CreateVastReplicationContent creates a new VastReplicationContent object.
// Returns an error if the object already exists or if the creation fails.
func (k *K8sClient) CreateVastReplicationContent(ctx context.Context, vrc *vastv1alpha1.VastReplicationContent) error {
	if err := k.client.Create(ctx, vrc); err != nil {
		return fmt.Errorf("failed to create VastReplicationContent %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}
	return nil
}

// PatchVastReplicationContentSpec patches the spec of an existing VRC.
// The caller applies the desired mutations to vrc before calling this method;
// PatchWithRetry re-fetches the object internally on conflict and re-applies
// the desired spec, so the caller's in-memory state must hold the full
// intended spec (not incremental deltas).
func (k *K8sClient) PatchVastReplicationContentSpec(ctx context.Context, vrc *vastv1alpha1.VastReplicationContent) error {
	desiredPVCs := vrc.Spec.PVCs
	desiredState := vrc.Spec.ReplicationState
	if err := k.PatchWithRetry(ctx, vrc, func() {
		vrc.Spec.PVCs = desiredPVCs
		vrc.Spec.ReplicationState = desiredState
	}); err != nil {
		return fmt.Errorf("failed to patch VastReplicationContent spec %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}
	return nil
}

// UpdateVastReplicationContentStatus persists the full status sub-resource,
// retrying on optimistic-concurrency conflicts.
func (k *K8sClient) UpdateVastReplicationContentStatus(ctx context.Context, vrc *vastv1alpha1.VastReplicationContent) error {
	if err := k.UpdateStatusWithRetry(ctx, vrc); err != nil {
		return fmt.Errorf("failed to update VastReplicationContent status %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}
	return nil
}

// ListVastReplicationContentsBySourceVR returns all VastReplicationContent objects whose
// source is the named VolumeReplication (matched by label).
func (k *K8sClient) ListVastReplicationContentsBySourceVR(ctx context.Context, namespace, vrName, vrNamespace string) ([]vastv1alpha1.VastReplicationContent, error) {
	return k.ListVastReplicationContentsByLabelSelector(ctx, namespace, map[string]string{
		common.LabelManagedBy:                        common.LabelManagedByValue,
		common.LabelSourceVolumeReplication:          vrName,
		common.LabelSourceVolumeReplicationNamespace: vrNamespace,
	})
}

// ListVastReplicationContentsBySourceVGR returns all VastReplicationContent objects whose
// source is the named VolumeGroupReplication (matched by label).
func (k *K8sClient) ListVastReplicationContentsBySourceVGR(ctx context.Context, namespace, vgrName, vgrNamespace string) ([]vastv1alpha1.VastReplicationContent, error) {
	return k.ListVastReplicationContentsByLabelSelector(ctx, namespace, map[string]string{
		common.LabelManagedBy:                             common.LabelManagedByValue,
		common.LabelSourceVolumeGroupReplication:          vgrName,
		common.LabelSourceVolumeGroupReplicationNamespace: vgrNamespace,
	})
}

// DeleteVastReplicationContent deletes a VastReplicationContent object.
// The object's finalizer keeps it alive until cleanup is complete.
func (k *K8sClient) DeleteVastReplicationContent(ctx context.Context, vrc *vastv1alpha1.VastReplicationContent) error {
	if err := k.client.Delete(ctx, vrc); err != nil && !k8serrors.IsNotFound(err) {
		return fmt.Errorf("failed to delete VastReplicationContent %s/%s: %w", vrc.Namespace, vrc.Name, err)
	}
	return nil
}

// listVastReplicationContentsByLabelSet is an internal helper using typed label.Set.
func (k *K8sClient) listVastReplicationContentsByLabelSet(ctx context.Context, namespace string, sel labels.Set) ([]vastv1alpha1.VastReplicationContent, error) {
	list := &vastv1alpha1.VastReplicationContentList{}
	if err := k.client.List(ctx, list,
		client.InNamespace(namespace),
		client.MatchingLabelsSelector{Selector: sel.AsSelector()},
	); err != nil {
		return nil, err
	}
	return list.Items, nil
}
