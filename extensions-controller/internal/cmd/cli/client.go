package cli

import (
	"context"
	"fmt"

	"github.com/fatih/color"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// Color helpers — enabled by default on TTY; root command may set color.NoColor = true.
var (
	Green  = color.New(color.FgGreen).SprintFunc()
	Yellow = color.New(color.FgYellow).SprintFunc()
	Red    = color.New(color.FgRed).SprintFunc()
	Cyan   = color.New(color.FgCyan).SprintFunc()
	Bold   = color.New(color.Bold).SprintFunc()
)

// ReplicationCRD constrains the two replication CRD pointer types.
type ReplicationCRD interface {
	*vastv1alpha1.VastStorageClassReplication | *vastv1alpha1.VastVolumeReplication
	client.Object
}

// PatchCRD snapshots obj, applies mutate, then sends a merge-patch to the API server.
func PatchCRD[T ReplicationCRD](ctx context.Context, k8s *k8sclient.K8sClient, obj T, mutate func(T)) error {
	base := client.MergeFrom(obj.DeepCopyObject().(client.Object))
	mutate(obj)
	return k8s.Client().Patch(ctx, obj, base)
}

// UpdateCRD applies mutate then performs a full Update.  Prefer this over
// PatchCRD when the change must immediately increment the resource generation
// and trigger controller reconciliation.
func UpdateCRD[T ReplicationCRD](ctx context.Context, k8s *k8sclient.K8sClient, obj T, mutate func(T)) error {
	mutate(obj)
	return k8s.Client().Update(ctx, obj)
}

// PatchReplicationSpec applies a merge-patch to update spec.action and/or
// spec.primaryStorageClass on the named VSCR or VVR object.
func PatchReplicationSpec(ctx context.Context, k8s *k8sclient.K8sClient, vscr, vvr, namespace string, action vastv1alpha1.ReplicationAction, primary string) error {
	switch {
	case vscr != "":
		obj, err := k8s.GetVastStorageClassReplication(ctx, vscr, namespace)
		if err != nil {
			return fmt.Errorf("VastStorageClassReplication %s/%s not found: %w", namespace, vscr, err)
		}
		return PatchCRD(ctx, k8s, obj, func(o *vastv1alpha1.VastStorageClassReplication) {
			if action != "" {
				o.Spec.Action = action
			}
			if primary != "" {
				o.Spec.PrimaryStorageClass = primary
			}
		})
	case vvr != "":
		obj, err := k8s.GetVastVolumeReplication(ctx, vvr, namespace)
		if err != nil {
			return fmt.Errorf("VastVolumeReplication %s/%s not found: %w", namespace, vvr, err)
		}
		return PatchCRD(ctx, k8s, obj, func(o *vastv1alpha1.VastVolumeReplication) {
			if action != "" {
				o.Spec.Action = action
			}
			if primary != "" {
				o.Spec.PrimaryStorageClass = primary
			}
		})
	default:
		return fmt.Errorf("must specify --vscr or --vvr")
	}
}

// UpdateReplicationSpec updates spec.action and/or spec.primaryStorageClass on
// the named VSCR or VVR object.  A full Update is used so the API server always
// increments the resource generation and immediately triggers reconciliation.
func UpdateReplicationSpec(ctx context.Context, k8s *k8sclient.K8sClient, vscr, vvr, namespace string, action vastv1alpha1.ReplicationAction, primary string) error {
	switch {
	case vscr != "":
		obj, err := k8s.GetVastStorageClassReplication(ctx, vscr, namespace)
		if err != nil {
			return fmt.Errorf("VastStorageClassReplication %s/%s not found: %w", namespace, vscr, err)
		}
		return UpdateCRD(ctx, k8s, obj, func(o *vastv1alpha1.VastStorageClassReplication) {
			if action != "" {
				o.Spec.Action = action
			}
			if primary != "" {
				o.Spec.PrimaryStorageClass = primary
			}
		})
	case vvr != "":
		obj, err := k8s.GetVastVolumeReplication(ctx, vvr, namespace)
		if err != nil {
			return fmt.Errorf("VastVolumeReplication %s/%s not found: %w", namespace, vvr, err)
		}
		return UpdateCRD(ctx, k8s, obj, func(o *vastv1alpha1.VastVolumeReplication) {
			if action != "" {
				o.Spec.Action = action
			}
			if primary != "" {
				o.Spec.PrimaryStorageClass = primary
			}
		})
	default:
		return fmt.Errorf("must specify --vscr or --vvr")
	}
}
