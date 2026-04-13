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

package controller

import (
	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	corev1 "k8s.io/api/core/v1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/event"
	"sigs.k8s.io/controller-runtime/pkg/predicate"
)

// isOwnedByVSCROrVVR returns true when obj carries an owner reference whose
// Kind is VastStorageClassReplication or VastVolumeReplication.  Those objects
// are exclusively managed by their own reconcilers.
func isOwnedByVSCROrVVR(obj client.Object) bool {
	for _, ref := range obj.GetOwnerReferences() {
		if ref.Kind == "VastStorageClassReplication" || ref.Kind == "VastVolumeReplication" {
			return true
		}
	}
	return false
}

// VastReplicationContentPredicate gates the VastReplicationContent reconciler.
//
//   - Create: always reconcile — covers both initial provisioning and controller
//     restarts where VRCs arrive as synthetic Create events.  Secondary VRCs are
//     included so the self-destruction check can fire (parent gone/terminating).
//   - Update: reconcile when the object is being deleted (regardless of state),
//     or when the spec generation changed.  Status-only updates are ignored.
//   - Delete: always reconcile — cleanup must run regardless of state.
func VastReplicationContentPredicate() predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(_ event.CreateEvent) bool { return true },
		UpdateFunc: func(e event.UpdateEvent) bool {
			if e.ObjectNew.GetDeletionTimestamp() != nil {
				return true
			}
			return e.ObjectNew.GetGeneration() != e.ObjectOld.GetGeneration()
		},
		DeleteFunc:  func(_ event.DeleteEvent) bool { return true },
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// volumeReplicationPredicate gates the replication_object_controller for
// VolumeReplication objects.
//
// Only VolumeReplications owned by VastVolumeReplication (or
// VastStorageClassReplication) are processed — user-created or csi-addons
// internal VRs are ignored entirely.
//
// A reconcile is triggered when:
//   - the VR is first created,
//   - its observed status.State changes (so the VRC replicationState is kept in sync)
//   - it acquires a DeletionTimestamp.
func volumeReplicationPredicate() predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(e event.CreateEvent) bool {
			return isOwnedByVSCROrVVR(e.Object)
		},
		UpdateFunc: func(e event.UpdateEvent) bool {
			if !isOwnedByVSCROrVVR(e.ObjectNew) {
				return false
			}
			if e.ObjectNew.GetDeletionTimestamp() != nil {
				return true
			}
			vrNew, ok := e.ObjectNew.(*replicationv1alpha1.VolumeReplication)
			if !ok {
				return false
			}
			vrOld, ok := e.ObjectOld.(*replicationv1alpha1.VolumeReplication)
			if !ok {
				return false
			}
			return vrNew.Status.State != vrOld.Status.State
		},
		DeleteFunc: func(e event.DeleteEvent) bool {
			return isOwnedByVSCROrVVR(e.Object)
		},
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// volumeGroupReplicationPredicate gates the replication_object_controller for
// VolumeGroupReplication objects.
//
// Only VolumeGroupReplications owned by VastStorageClassReplication (or
// VastVolumeReplication) are processed.
//
// A reconcile is triggered when:
//   - the VGR is first created,
//   - its PVC membership list changes (csi-addons populates this after the
//     group is established — the controller needs it to build the VRC),
//   - its observed status.State changes
//   - it acquires a DeletionTimestamp.
func volumeGroupReplicationPredicate() predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(e event.CreateEvent) bool {
			return isOwnedByVSCROrVVR(e.Object)
		},
		UpdateFunc: func(e event.UpdateEvent) bool {
			if !isOwnedByVSCROrVVR(e.ObjectNew) {
				return false
			}
			if e.ObjectNew.GetDeletionTimestamp() != nil {
				return true
			}
			vgrNew, ok := e.ObjectNew.(*replicationv1alpha1.VolumeGroupReplication)
			if !ok {
				return false
			}
			vgrOld, ok := e.ObjectOld.(*replicationv1alpha1.VolumeGroupReplication)
			if !ok {
				return false
			}
			// Always react to PVC list changes so VRC.Spec.PVCs stays in sync.
			if vgrPVCListChanged(vgrOld.Status.PersistentVolumeClaimsRefList, vgrNew.Status.PersistentVolumeClaimsRefList) {
				return true
			}
			// For state transitions, require VolumeReplicationName to be set so we
			// don't act on transient intermediate states before csi-addons has
			// finished establishing the VolumeGroupReplicationContent.
			if vgrNew.Spec.VolumeReplicationName == "" {
				return false
			}
			return vgrNew.Status.State != vgrOld.Status.State
		},
		DeleteFunc: func(e event.DeleteEvent) bool {
			return isOwnedByVSCROrVVR(e.Object)
		},
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// ownedVRPredicate fires a reconcile on the owning VastVolumeReplication when
// an owned VolumeReplication:
//   - acquires a DeletionTimestamp, or
//   - transitions to the confirmed-primary state: both Spec.ReplicationState ==
//     Primary (desired) and Status.State == PrimaryState (current) are true
//     after the update.
func ownedVRPredicate() predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(_ event.CreateEvent) bool { return false },
		UpdateFunc: func(e event.UpdateEvent) bool {
			if e.ObjectOld.GetDeletionTimestamp() == nil && e.ObjectNew.GetDeletionTimestamp() != nil {
				return true
			}
			vrNew, ok := e.ObjectNew.(*replicationv1alpha1.VolumeReplication)
			if !ok {
				return false
			}
			vrOld, ok := e.ObjectOld.(*replicationv1alpha1.VolumeReplication)
			if !ok {
				return false
			}
			// Only reconcile when the VR has just been confirmed as primary
			// (desired == primary AND current == primary).
			return k8sclient.IsVRConfirmedPrimary(vrNew) && !k8sclient.IsVRConfirmedPrimary(vrOld)
		},
		DeleteFunc:  func(_ event.DeleteEvent) bool { return false },
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// ownedVGRPredicate fires a reconcile on the owning VastStorageClassReplication
// when an owned VolumeGroupReplication:
//   - acquires a DeletionTimestamp, or
//   - transitions to the confirmed-primary state: both Spec.ReplicationState ==
//     Primary (desired) and Status.State == PrimaryState (current) are true
//     after the update.
func ownedVGRPredicate() predicate.Predicate {
	return predicate.Funcs{
		CreateFunc: func(_ event.CreateEvent) bool { return false },
		UpdateFunc: func(e event.UpdateEvent) bool {
			if e.ObjectOld.GetDeletionTimestamp() == nil && e.ObjectNew.GetDeletionTimestamp() != nil {
				return true
			}
			vgrNew, ok := e.ObjectNew.(*replicationv1alpha1.VolumeGroupReplication)
			if !ok {
				return false
			}
			vgrOld, ok := e.ObjectOld.(*replicationv1alpha1.VolumeGroupReplication)
			if !ok {
				return false
			}
			// Only reconcile when the VGR has just been confirmed as primary
			// (desired == primary AND current == primary).
			return k8sclient.IsVGRConfirmedPrimary(vgrNew) && !k8sclient.IsVGRConfirmedPrimary(vgrOld)
		},
		DeleteFunc:  func(_ event.DeleteEvent) bool { return false },
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// confirmedPrimaryTransitionPredicate fires for the PVCRemapReconciler when a
// VolumeReplication or VolumeGroupReplication is, or becomes, confirmed-primary
// (spec.replicationState == primary AND status.state == primary).
//
// Triggers:
//   - Create: fires on controller startup for objects that are already
//     confirmed-primary (informer replays all existing objects as synthetic
//     Create events, ensuring remap runs immediately after a pod restart).
//   - Update (transition): fires when the object enters confirmed-primary state.
//   - Update (VGR PVC list change): fires when a VGR is already confirmed-primary
//     and its PVC membership list changes — new mirror PVCs have been added.
//
// Deletion events are intentionally ignored; the remap reconciler must not run
// during object cleanup.
func confirmedPrimaryTransitionPredicate() predicate.Predicate {
	isConfirmed := func(obj client.Object) bool {
		switch o := obj.(type) {
		case *replicationv1alpha1.VolumeReplication:
			return k8sclient.IsVRConfirmedPrimary(o)
		case *replicationv1alpha1.VolumeGroupReplication:
			return k8sclient.IsVGRConfirmedPrimary(o)
		}
		return false
	}
	return predicate.Funcs{
		// Startup: reconcile any VGR/VR that is already confirmed-primary so
		// remap is applied without waiting for the next state-change event.
		CreateFunc: func(e event.CreateEvent) bool {
			return isOwnedByVSCROrVVR(e.Object) && isConfirmed(e.Object)
		},
		UpdateFunc: func(e event.UpdateEvent) bool {
			if !isOwnedByVSCROrVVR(e.ObjectNew) {
				return false
			}
			// Trigger on any transition into confirmed-primary.
			if !isConfirmed(e.ObjectOld) && isConfirmed(e.ObjectNew) {
				return true
			}
			// For VGR: also trigger when already confirmed-primary and the PVC
			// membership list changes — mirror PVCs may have just been provisioned.
			if isConfirmed(e.ObjectNew) {
				vgrNew, ok := e.ObjectNew.(*replicationv1alpha1.VolumeGroupReplication)
				if !ok {
					return false
				}
				vgrOld, ok := e.ObjectOld.(*replicationv1alpha1.VolumeGroupReplication)
				if !ok {
					return false
				}
				return vgrPVCListChanged(vgrOld.Status.PersistentVolumeClaimsRefList, vgrNew.Status.PersistentVolumeClaimsRefList)
			}
			return false
		},
		DeleteFunc:  func(_ event.DeleteEvent) bool { return false },
		GenericFunc: func(_ event.GenericEvent) bool { return false },
	}
}

// vgrPVCListChanged returns true if the PVC membership of a VolumeGroupReplication
// has changed between two status snapshots.
func vgrPVCListChanged(old, new []corev1.LocalObjectReference) bool {
	if len(old) != len(new) {
		return true
	}
	oldNames := make(map[string]struct{}, len(old))
	for _, ref := range old {
		oldNames[ref.Name] = struct{}{}
	}
	for _, ref := range new {
		if _, ok := oldNames[ref.Name]; !ok {
			return true
		}
	}
	return false
}
