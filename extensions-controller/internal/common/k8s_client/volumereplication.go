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
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"go.uber.org/zap"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/util/retry"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// GetVolumeReplication fetches a VolumeReplication by name and namespace.
func (k *K8sClient) GetVolumeReplication(ctx context.Context, name, namespace string) (*replicationv1alpha1.VolumeReplication, error) {
	vr := &replicationv1alpha1.VolumeReplication{}
	if err := k.GetObject(ctx, name, namespace, vr); err != nil {
		if apierrors.IsNotFound(err) {
			k.logger.Debug("VolumeReplication not found",
				zap.String("name", name),
				zap.String("namespace", namespace))
		} else {
			k.logger.Error("Failed to get VolumeReplication",
				zap.Error(err),
				zap.String("name", name),
				zap.String("namespace", namespace))
		}
		return nil, err
	}
	return vr, nil
}

// GetVolumeGroupReplication fetches a VolumeGroupReplication by name and namespace.
func (k *K8sClient) GetVolumeGroupReplication(ctx context.Context, name, namespace string) (*replicationv1alpha1.VolumeGroupReplication, error) {
	vgr := &replicationv1alpha1.VolumeGroupReplication{}
	if err := k.GetObject(ctx, name, namespace, vgr); err != nil {
		if apierrors.IsNotFound(err) {
			k.logger.Debug("VolumeGroupReplication not found",
				zap.String("name", name),
				zap.String("namespace", namespace))
		} else {
			k.logger.Error("Failed to get VolumeGroupReplication",
				zap.Error(err),
				zap.String("name", name),
				zap.String("namespace", namespace))
		}
		return nil, err
	}
	return vgr, nil
}

// EnsureVolumeReplication ensures a VolumeReplication exists.
// Returns (true, nil) when the object was freshly created, (false, nil) when it
// already existed, and (false, err) on any API error.
func (k *K8sClient) EnsureVolumeReplication(ctx context.Context, vr *replicationv1alpha1.VolumeReplication) (bool, error) {
	_, err := k.GetVolumeReplication(ctx, vr.Name, vr.Namespace)
	if err == nil {
		return false, nil
	}
	if !apierrors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing VolumeReplication %s/%s: %w", vr.Namespace, vr.Name, err)
	}

	if err := k.client.Create(ctx, vr); err != nil {
		if apierrors.IsAlreadyExists(err) {
			k.logger.Info("VolumeReplication was created by another process",
				zap.String("name", vr.Name),
				zap.String("namespace", vr.Namespace))
			return false, nil
		}
		return false, fmt.Errorf("failed to create VolumeReplication %s/%s: %w", vr.Namespace, vr.Name, err)
	}
	return true, nil
}

// EnsureVolumeGroupReplication ensures a VolumeGroupReplication exists.
// Returns (true, nil) when the object was freshly created, (false, nil) when it
// already existed, and (false, err) on any API error.
func (k *K8sClient) EnsureVolumeGroupReplication(ctx context.Context, vgr *replicationv1alpha1.VolumeGroupReplication) (bool, error) {
	_, err := k.GetVolumeGroupReplication(ctx, vgr.Name, vgr.Namespace)
	if err == nil {
		return false, nil
	}
	if !apierrors.IsNotFound(err) {
		return false, fmt.Errorf("failed to check for existing VolumeGroupReplication %s/%s: %w", vgr.Namespace, vgr.Name, err)
	}

	if err := k.client.Create(ctx, vgr); err != nil {
		if apierrors.IsAlreadyExists(err) {
			k.logger.Info("VolumeGroupReplication was created by another process",
				zap.String("name", vgr.Name),
				zap.String("namespace", vgr.Namespace))
			return false, nil
		}
		return false, fmt.Errorf("failed to create VolumeGroupReplication %s/%s: %w", vgr.Namespace, vgr.Name, err)
	}
	return true, nil
}

// PatchVolumeReplicationState sets spec.replicationState on the given
// VolumeReplication.  It retries on conflict by re-fetching the object before
// each attempt so the patch is always applied to the latest resource version.
func (k *K8sClient) PatchVolumeReplicationState(ctx context.Context, vr *replicationv1alpha1.VolumeReplication, state replicationv1alpha1.ReplicationState) error {
	name, ns := vr.Name, vr.Namespace
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		fresh := &replicationv1alpha1.VolumeReplication{}
		if err := k.client.Get(ctx, client.ObjectKey{Name: name, Namespace: ns}, fresh); err != nil {
			return err
		}
		if fresh.Spec.ReplicationState == state {
			return nil
		}
		patch := client.MergeFrom(fresh.DeepCopy())
		fresh.Spec.ReplicationState = state
		if err := k.client.Patch(ctx, fresh, patch); err != nil {
			return fmt.Errorf("failed to patch VolumeReplication %s/%s replicationState to %q: %w",
				ns, name, state, err)
		}
		return nil
	})
}

// PatchVolumeGroupReplicationState sets spec.replicationState on the given
// VolumeGroupReplication.  It retries on conflict by re-fetching the object
// before each attempt.
func (k *K8sClient) PatchVolumeGroupReplicationState(ctx context.Context, vgr *replicationv1alpha1.VolumeGroupReplication, state replicationv1alpha1.ReplicationState) error {
	name, ns := vgr.Name, vgr.Namespace
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		fresh := &replicationv1alpha1.VolumeGroupReplication{}
		if err := k.client.Get(ctx, client.ObjectKey{Name: name, Namespace: ns}, fresh); err != nil {
			return err
		}
		if fresh.Spec.ReplicationState == state {
			return nil
		}
		patch := client.MergeFrom(fresh.DeepCopy())
		fresh.Spec.ReplicationState = state
		if err := k.client.Patch(ctx, fresh, patch); err != nil {
			return fmt.Errorf("failed to patch VolumeGroupReplication %s/%s replicationState to %q: %w",
				ns, name, state, err)
		}
		return nil
	})
}

// PatchVastReplicationContentState sets spec.replicationState on the given
// VastReplicationContent.  It retries on conflict by re-fetching the object
// before each attempt.
func (k *K8sClient) PatchVastReplicationContentState(ctx context.Context, vrc *vastv1alpha1.VastReplicationContent, state string) error {
	name, ns := vrc.Name, vrc.Namespace
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		fresh := &vastv1alpha1.VastReplicationContent{}
		if err := k.client.Get(ctx, client.ObjectKey{Name: name, Namespace: ns}, fresh); err != nil {
			return err
		}
		if fresh.Spec.ReplicationState == state {
			return nil
		}
		patch := client.MergeFrom(fresh.DeepCopy())
		fresh.Spec.ReplicationState = state
		if err := k.client.Patch(ctx, fresh, patch); err != nil {
			return fmt.Errorf("failed to patch VastReplicationContent %s/%s replicationState to %q: %w",
				ns, name, state, err)
		}
		k.logger.Info("patched VastReplicationContent replicationState",
			zap.String("vrc", ns+"/"+name),
			zap.String("state", state))
		return nil
	})
}

// ListVolumeReplicationsByLabelSelector lists all VolumeReplications in a namespace that match the given label selector.
func (k *K8sClient) ListVolumeReplicationsByLabelSelector(ctx context.Context, namespace string, selector map[string]string) ([]replicationv1alpha1.VolumeReplication, error) {
	vrList := &replicationv1alpha1.VolumeReplicationList{}
	opts := []client.ListOption{
		client.InNamespace(namespace),
		client.MatchingLabels(selector),
	}
	if err := k.client.List(ctx, vrList, opts...); err != nil {
		return nil, err
	}
	return vrList.Items, nil
}

// DeleteVolumeReplication issues a delete request for a VolumeReplication.
// A NotFound error is silently ignored (idempotent).
func (k *K8sClient) DeleteVolumeReplication(ctx context.Context, name, namespace string) error {
	vr := &replicationv1alpha1.VolumeReplication{}
	vr.Name = name
	vr.Namespace = namespace
	if err := k.client.Delete(ctx, vr); err != nil && !apierrors.IsNotFound(err) {
		return fmt.Errorf("failed to delete VolumeReplication %s/%s: %w", namespace, name, err)
	}
	return nil
}

// DeleteVolumeGroupReplication issues a delete request for a VolumeGroupReplication.
// A NotFound error is silently ignored (idempotent).
func (k *K8sClient) DeleteVolumeGroupReplication(ctx context.Context, name, namespace string) error {
	vgr := &replicationv1alpha1.VolumeGroupReplication{}
	vgr.Name = name
	vgr.Namespace = namespace
	if err := k.client.Delete(ctx, vgr); err != nil && !apierrors.IsNotFound(err) {
		return fmt.Errorf("failed to delete VolumeGroupReplication %s/%s: %w", namespace, name, err)
	}
	return nil
}

// IsVRConfirmedPrimary reports whether a VolumeReplication has both its desired
// state (Spec.ReplicationState) and its observed state (Status.State) set to
// Primary, meaning the cluster has fully acknowledged the primary role.
func IsVRConfirmedPrimary(vr *replicationv1alpha1.VolumeReplication) bool {
	return vr.Spec.ReplicationState == replicationv1alpha1.Primary &&
		vr.Status.State == replicationv1alpha1.PrimaryState
}

// IsVGRConfirmedPrimary reports whether a VolumeGroupReplication has both its
// desired state (Spec.ReplicationState) and its observed state (Status.State)
// set to Primary.
func IsVGRConfirmedPrimary(vgr *replicationv1alpha1.VolumeGroupReplication) bool {
	return vgr.Spec.ReplicationState == replicationv1alpha1.Primary &&
		vgr.Status.State == replicationv1alpha1.PrimaryState
}

// ListVolumeGroupReplicationsByLabelSelector lists all VolumeGroupReplications in a namespace that match the given label selector.
func (k *K8sClient) ListVolumeGroupReplicationsByLabelSelector(ctx context.Context, namespace string, selector map[string]string) ([]replicationv1alpha1.VolumeGroupReplication, error) {
	vgrList := &replicationv1alpha1.VolumeGroupReplicationList{}
	opts := []client.ListOption{
		client.InNamespace(namespace),
		client.MatchingLabels(selector),
	}
	if err := k.client.List(ctx, vgrList, opts...); err != nil {
		return nil, err
	}
	return vgrList.Items, nil
}
