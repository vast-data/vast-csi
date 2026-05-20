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

// Package v1alpha1 contains the VAST CSI extensions controller API types.
package v1alpha1

import (
	"context"
	"fmt"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	// DestinationKindVolumeReplication is the Kind value for a mirrored VolumeReplication.
	DestinationKindVolumeReplication = "VolumeReplication"

	// DestinationKindVolumeGroupReplication is the Kind value for a mirrored VolumeGroupReplication.
	DestinationKindVolumeGroupReplication = "VolumeGroupReplication"

	// LabelSourceVolumeReplication is the label key that stores the parent
	// VolumeReplication name on a VastReplicationContent object.
	LabelSourceVolumeReplication = "vastdata.com/source-volume-replication"

	// LabelSourceVolumeGroupReplication is the label key that stores the parent
	// VolumeGroupReplication name on a VastReplicationContent object.
	LabelSourceVolumeGroupReplication = "vastdata.com/source-volume-group-replication"

	// LabelSourceVSCR is set on VastReplicationContent objects whose parent
	// VolumeGroupReplication was created by a VastStorageClassReplication.
	LabelSourceVSCR = "vastdata.com/source-vscr"

	// LabelSourceVVR is set on VastReplicationContent objects whose parent
	// VolumeReplication was created by a VastVolumeReplication.
	LabelSourceVVR = "vastdata.com/source-vvr"
)

// ProvisionerType identifies which VAST CSI provisioner handles a VastReplicationContent.
// Determined once at creation time from the destination StorageClass.
// +kubebuilder:validation:Enum=Block;File
type ProvisionerType string

const (
	// ProvisionerTypeBlock selects the block (iSCSI/NVMe) provisioner.
	ProvisionerTypeBlock ProvisionerType = "Block"

	// ProvisionerTypeFile selects the file (NFS/SMB) provisioner.
	ProvisionerTypeFile ProvisionerType = "File"
)

// PVCList is a list of PVC names.
type PVCList = DisplayableList

// VastReplicationContentSpec defines the desired state of VastReplicationContent.
// Fields are managed by the ReplicationObjectReconciler (parent controller).
//
// Most fields are immutable after creation (enforced by the API server via CEL
// validation rules).  Only spec.pvcs and spec.replicationState may change after
// the object is first written.
type VastReplicationContentSpec struct {
	// StorageClass is the name of the StorageClass this content object is
	// responsible for.  Set at creation time and never changed.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="storageClass is immutable"
	StorageClass string `json:"storageClass"`

	// ProvisionerType indicates whether this content is managed by the block
	// or file VAST CSI provisioner.  Determined once at creation time from the
	// destination StorageClass (presence of the "subsystem" parameter → Block).
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="provisionerType is immutable"
	ProvisionerType ProvisionerType `json:"provisionerType"`

	// Kind identifies the kind of the mirrored destination object
	// (VolumeReplication or VolumeGroupReplication).
	// Set at creation time and never changed.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="kind is immutable"
	// +optional
	Kind string `json:"kind,omitempty"`

	// SyncPVCPV mirrors the same field from the parent
	// VastStorageClassReplication or VastVolumeReplication.
	// Set at creation time and never changed.
	// When true the provisioner creates/deletes static PV+PVC pairs on the
	// destination cluster.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="syncPVCPV is immutable"
	// +optional
	SyncPVCPV bool `json:"syncPVCPV,omitempty"`

	// DestVolReclaimPolicy mirrors the same field from the parent
	// VastStorageClassReplication or VastVolumeReplication.
	// Set at creation time and never changed.
	// Controls whether destination VAST objects are deleted on VRC deletion.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="destVolReclaimPolicy is immutable"
	// +kubebuilder:default=Retain
	// +optional
	DestVolReclaimPolicy DestVolReclaimPolicy `json:"destVolReclaimPolicy,omitempty"`

	// ReplicationPath is the sourceDir of the VAST protected path (ppath)
	// associated with this replication.  Set at creation time; used by cleanup
	// logic even after the parent object is gone.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="replicationPath is immutable"
	ReplicationPath string `json:"replicationPath"`

	// ProtectionPolicyName is the name of the VAST protection policy associated
	// with this replication.  Set at creation time and never changed.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="protectionPolicyName is immutable"
	ProtectionPolicyName string `json:"protectionPolicyName"`

	// ProtectedPathName is the name of the VAST protected path (ppath) on the
	// source cluster.  Resolved at creation time by querying the VAST cluster.
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="protectedPathName is immutable"
	ProtectedPathName string `json:"protectedPathName"`

	// PVCs is the list of PVC names from the parent VolumeReplication or
	// VolumeGroupReplication.  Updated whenever the parent's PVC membership
	// changes; a change here bumps metadata.generation and triggers re-provisioning.
	// +optional
	PVCs PVCList `json:"pvcs,omitempty"`

	// ReplicationState mirrors the parent VR/VGR's replicationState so the
	// provisioner knows whether this cluster is the active source.
	// Updated whenever the parent's replication state changes.
	// +optional
	ReplicationState string `json:"replicationState,omitempty"`
}

// VastReplicationContentStatus defines the observed state of VastReplicationContent.
// Fields are managed by the VastReplicationContentReconciler.
type VastReplicationContentStatus struct {
	// Provisioned is true once all resources for the StorageClass have been
	// successfully created.
	// +optional
	Provisioned bool `json:"provisioned,omitempty"`

	// ObservedGeneration is the metadata.generation of the spec that was last
	// successfully reconciled.  When ObservedGeneration < metadata.generation
	// the reconciler knows the spec has changed and re-runs provisioning.
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// PVCsPreview is a human-readable summary of spec.pvcs, formatted by
	// PVCList.String() (e.g. `["pvc1", "pvc2" ... +2 more]`).
	// Kept in status so the kubectl printcolumn can display it via a simple
	// JSONPath expression without invoking Go methods.
	// +optional
	PVCsPreview string `json:"pvcsPreview,omitempty"`

	// PVCs is the PVC list from the last successfully reconciled spec.
	// Compared against spec.pvcs at the start of each reconcile to compute
	// which PVCs were added (PVCsToCreate) and which were removed (PVCsToDelete).
	// +optional
	PVCs PVCList `json:"pvcs,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Namespaced,shortName=vrcon
// +kubebuilder:printcolumn:name="Type",type=string,JSONPath=`.spec.provisionerType`
// +kubebuilder:printcolumn:name="Storage Class",type=string,JSONPath=`.spec.storageClass`
// +kubebuilder:printcolumn:name="Kind",type=string,JSONPath=`.spec.kind`
// +kubebuilder:printcolumn:name="Source PVCs",type=string,JSONPath=`.status.pvcsPreview`
// +kubebuilder:printcolumn:name="State",type=string,JSONPath=`.spec.replicationState`
// +kubebuilder:printcolumn:name="Provisioned",type=boolean,JSONPath=`.status.provisioned`
// +kubebuilder:printcolumn:name="Replication Path",type=string,JSONPath=`.spec.replicationPath`
// +kubebuilder:printcolumn:name="Protection Policy",type=string,JSONPath=`.spec.protectionPolicyName`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// VastReplicationContent is the internal CRD that holds the full provisioning
// state for one StorageClass mirroring a parent VolumeReplication or
// VolumeGroupReplication.
//
// Lifecycle:
//
//   - ReplicationObjectReconciler creates one VastReplicationContent per
//     StorageClass, sets an owner reference to the parent ("main")
//     VolumeReplication or VolumeGroupReplication, and keeps spec.pvcs
//     up-to-date whenever the parent's membership changes.
//   - VastReplicationContentReconciler provisions the mirrored resources when
//     metadata.generation > status.observedGeneration, then records
//     ReplicationPath and ProtectionPolicyName in the status so cleanup can
//     proceed even if the mirrored objects are already gone.
//   - Cleanup is driven by this object's finalizer.  The parent name (taken
//     from the owner reference) is used as a label key to find all managed
//     resources for that specific StorageClass.
//
// Deletion scenarios:
//
//  1. Delete one VastReplicationContent → cleans only resources for that SC.
//  2. Delete the parent VR/VGR → Kubernetes GC cascades to all owned
//     VastReplicationContent objects via owner-reference garbage collection.
type VastReplicationContent struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   VastReplicationContentSpec   `json:"spec,omitempty"`
	Status VastReplicationContentStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// VastReplicationContentList contains a list of VastReplicationContent.
type VastReplicationContentList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []VastReplicationContent `json:"items"`
}

// String returns a concise human-readable identifier for log messages and
// error strings, of the form "namespace/name [StorageClass: sc-name]".
func (vrc *VastReplicationContent) String() string {
	return fmt.Sprintf("%s/%s [StorageClass: %s]", vrc.Namespace, vrc.Name, vrc.Spec.StorageClass)
}

// SourceName returns the name of the main ("parent") VolumeReplication or
// VolumeGroupReplication stored in the object's labels, based on Kind.
func (vrc *VastReplicationContent) SourceName() string {
	switch vrc.Spec.Kind {
	case DestinationKindVolumeReplication:
		return vrc.Labels[LabelSourceVolumeReplication]
	case DestinationKindVolumeGroupReplication:
		return vrc.Labels[LabelSourceVolumeGroupReplication]
	default:
		return ""
	}
}

// VRCLister lists VastReplicationContent objects in a namespace that match the
// given label selector.  Callers inject a concrete implementation so this
// package stays free of any Kubernetes client dependency.
type VRCLister func(ctx context.Context, namespace string, labels map[string]string) ([]VastReplicationContent, error)

// GetConstellationVRCs returns all VastReplicationContent objects in the same constellation
// as vrc, including vrc itself.  Constellations are identified by the
// LabelSourceVSCR or LabelSourceVVR label set at creation time.
// Returns nil (no error) for standalone VRCs that carry neither label.
func (vrc *VastReplicationContent) GetConstellationVRCs(ctx context.Context, lister VRCLister) ([]*VastReplicationContent, error) {
	var labelKey, labelVal string
	if v := vrc.Labels[LabelSourceVSCR]; v != "" {
		labelKey, labelVal = LabelSourceVSCR, v
	} else if v := vrc.Labels[LabelSourceVVR]; v != "" {
		labelKey, labelVal = LabelSourceVVR, v
	} else {
		return nil, nil
	}

	candidates, err := lister(ctx, vrc.Namespace, map[string]string{labelKey: labelVal})
	if err != nil {
		return nil, fmt.Errorf("failed to list constellation VRCs: %w", err)
	}

	peers := make([]*VastReplicationContent, 0, len(candidates))
	for i := range candidates {
		peers = append(peers, &candidates[i])
	}
	return peers, nil
}

func init() {
	SchemeBuilder.Register(&VastReplicationContent{}, &VastReplicationContentList{})
}
