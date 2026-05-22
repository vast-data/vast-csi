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
	"time"

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

// WaitForVRC polls until a VastReplicationContent with the given name exists in
// namespace, or until ctx is cancelled or timeout elapses.
//
// It is used after freshly creating a VR/VGR to ensure the
// ReplicationObjectReconciler has created the corresponding VRC before the
// next sibling VR/VGR is created.  Secondary VRCs must find the primary VRC
// already present in the constellation when they first reconcile so that
// classifyConstellationPVCs can locate the source PVC and create the mirror.
func (k *K8sClient) WaitForVRC(ctx context.Context, namespace, name string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for {
		_, err := k.GetVastReplicationContent(ctx, name, namespace)
		if err == nil {
			return nil
		}
		if !k8serrors.IsNotFound(err) {
			return fmt.Errorf("checking for VRC %s/%s: %w", namespace, name, err)
		}
		if time.Now().After(deadline) {
			return fmt.Errorf("timed out waiting for VRC %s/%s to be created after %s", namespace, name, timeout)
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(200 * time.Millisecond):
		}
	}
}

// TouchConstellationVRCs annotates every VastReplicationContent in the VSCR
// constellation (primary + all secondaries) with the current timestamp, which
// causes the VRC controller to immediately re-queue each one.
//
// Returns the names of every VRC that was successfully touched so the caller
// can emit per-VRC events or log them.  VRCs that do not exist yet are silently
// skipped and are not included in the returned slice.
func (k *K8sClient) TouchConstellationVRCs(
	ctx context.Context,
	vscr *vastv1alpha1.VastStorageClassReplication,
) ([]string, error) {
	return k.touchVRCsForStorageClasses(ctx, vscr, vscr.Spec.AllStorageClasses())
}

// TouchSecondaryVRCs annotates every non-primary VastReplicationContent in the
// VSCR constellation with the current timestamp so the VRC controller
// immediately re-queues them.
//
// Returns the names of every VRC that was successfully touched.  Used when new
// primary PVCs appear and secondary VRCs must create their mirror PVCs without
// waiting for their own VGR to change.
func (k *K8sClient) TouchSecondaryVRCs(
	ctx context.Context,
	vscr *vastv1alpha1.VastStorageClassReplication,
) ([]string, error) {
	var secondarySCs []string
	for _, sc := range vscr.Spec.AllStorageClasses() {
		if sc != vscr.Spec.PrimaryStorageClass {
			secondarySCs = append(secondarySCs, sc)
		}
	}
	return k.touchVRCsForStorageClasses(ctx, vscr, secondarySCs)
}

// touchVRCsForStorageClasses is the shared implementation used by
// TouchConstellationVRCs and TouchSecondaryVRCs.
func (k *K8sClient) touchVRCsForStorageClasses(
	ctx context.Context,
	vscr *vastv1alpha1.VastStorageClassReplication,
	storageClasses []string,
) ([]string, error) {
	ts := time.Now().UTC().Format(time.RFC3339)
	var touched []string
	for _, scName := range storageClasses {
		vrcName := vscr.Name + "-" + scName
		vrc, err := k.GetVastReplicationContent(ctx, vrcName, vscr.Namespace)
		if err != nil {
			if k8serrors.IsNotFound(err) {
				continue // not yet provisioned — skip silently
			}
			return touched, fmt.Errorf("get VRC %s/%s: %w", vscr.Namespace, vrcName, err)
		}
		if err := k.SetAnnotationAndUpdate(ctx, vrc, common.AnnotationResyncRequestedAt, ts); err != nil {
			return touched, fmt.Errorf("touch VRC %s/%s: %w", vscr.Namespace, vrcName, err)
		}
		touched = append(touched, vrcName)
	}
	return touched, nil
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
