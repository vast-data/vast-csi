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

package v1alpha1

import (
	"fmt"
	"sort"
	"strings"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// FailoverAction describes the type of failover to execute when the primary
// StorageClass changes.
//
// +kubebuilder:validation:Enum=ungracefulFailover;gracefulFailover
type FailoverAction string

// DestVolReclaimPolicy controls whether the destination VAST objects
// (block volumes or file views/quotas) created by the operator are
// deleted when the parent VVR or VSCR is deleted.
//
// +kubebuilder:validation:Enum=Retain;Delete
type DestVolReclaimPolicy string

const (
	// DestVolReclaimPolicyRetain keeps destination VAST objects after the
	// VVR/VSCR is deleted.  This is the default and the safe choice.
	DestVolReclaimPolicyRetain DestVolReclaimPolicy = "Retain"

	// DestVolReclaimPolicyDelete removes destination VAST objects when the
	// VVR/VSCR is deleted.
	DestVolReclaimPolicyDelete DestVolReclaimPolicy = "Delete"
)

const (
	FailoverTypeUngraceful FailoverAction = "ungracefulFailover"
	FailoverTypeGraceful   FailoverAction = "gracefulFailover"
)

// ReplicationAction is kept for backward compatibility with the gRPC proto
// mapping.  New code should use FailoverAction.
//
// Deprecated: use FailoverAction.
type ReplicationAction = FailoverAction

const (
	ActionUngracefulFailover = FailoverTypeUngraceful
	ActionGracefulFailover   = FailoverTypeGraceful
)

// SyncStatus values for VastStorageClassReplicationStatus.SyncStatus and
// VastVolumeReplicationStatus.SyncStatus.
const (
	// SyncStatusCompleted means the VolumeGroupReplication / VolumeReplication
	// for the primary StorageClass reports State=Primary.
	SyncStatusCompleted = "Completed"

	// SyncStatusInProgress means replication is active but the primary state
	// has not yet been reached.
	SyncStatusInProgress = "InProgress"

	// SyncStatusUnreachable means the controller cannot reach the VAST cluster
	// (network timeout, dial error, etc.).
	SyncStatusUnreachable = "Unreachable"

	// SyncStatusError means the VAST cluster returned an API error (4xx / 5xx).
	SyncStatusError = "Error"

	// SyncStatusInvalid means the resource spec is misconfigured and must be
	// corrected by the user before replication can proceed.
	SyncStatusInvalid = "Invalid"

	// SyncStatusDeleting means the resource has been marked for deletion and
	// its finalizer cleanup is in progress.
	SyncStatusDeleting = "Deleting"

	// SyncStatusFailed means a permanent infrastructure error occurred (e.g.
	// the VAST protected path settled in a "failed" state) and requires user
	// intervention.  The controller keeps retrying, so the status will clear
	// automatically once the underlying issue is resolved.
	SyncStatusFailed = "Failed"
)

// VastStorageClassReplicationSpec defines the desired state of VastStorageClassReplication.
type VastStorageClassReplicationSpec struct {
	// PrimaryStorageClass is the StorageClass that is currently acting as the
	// active (primary) replica.  The VolumeGroupReplication for this class gets
	// replicationState=primary; all others get replicationState=secondary.
	// +kubebuilder:validation:Required
	PrimaryStorageClass string `json:"primaryStorageClass"`

	// ProtectionTopology defines the undirected replication mesh.  Each entry
	// connects two clusters bidirectionally via a shared PeerName.  The mesh
	// must be complete: for n distinct clusters exactly n*(n-1)/2 entries are
	// required (one per unordered cluster pair).
	// Example for 2 clusters: 1 entry  (A–B).
	// Example for 3 clusters: 3 entries (A–B, A–C, B–C).
	// Example for 4 clusters: 6 entries (A–B, A–C, A–D, B–C, B–D, C–D).
	// The full StorageClass list is derived automatically from these entries.
	// +kubebuilder:validation:MinItems=1
	ProtectionTopology []ReplicationTarget `json:"protectionTopology"`

	// ProtectionPolicyTemplate defines the schedule for operator-created
	// NATIVE_REPLICATION protection policies.  The operator creates one policy
	// per topology entry side and uses it as a replication stream on the ppath.
	// +kubebuilder:validation:Required
	ProtectionPolicyTemplate ProtectionPolicyTemplate `json:"protectionPolicyTemplate"`

	// FailoverType is the type of failover to execute when the primary StorageClass
	// changes.  Supported values: ungracefulFailover (default), gracefulFailover.
	// +kubebuilder:default=ungracefulFailover
	FailoverType FailoverAction `json:"failoverType"`

	// Resync is a one-shot trigger: set to true to request an immediate resync.
	// +optional
	Resync bool `json:"resync,omitempty"`

	// SyncIntervalSeconds is the replication sync interval in seconds.
	// When omitted or zero, the interval is derived from the "every" field of
	// the first protectionPolicyTemplate entry.
	// +kubebuilder:validation:Minimum=0
	// +optional
	SyncIntervalSeconds int64 `json:"syncIntervalSeconds,omitempty"`

	// PVCRemap controls whether PVCs are remapped to the new primary on failover.
	// +kubebuilder:default=false
	PVCRemap bool `json:"pvcRemap"`

	// SyncPVCPV controls whether the controller creates/deletes static
	// PV+PVC pairs on each destination cluster.  Defaults to true.
	// +kubebuilder:default=true
	SyncPVCPV bool `json:"syncPVCPV"`

	// DestVolReclaimPolicy controls whether destination VAST objects (block
	// volumes or file views/quotas) are deleted when the VSCR is deleted.
	// Defaults to Retain.
	// +kubebuilder:default=Retain
	DestVolReclaimPolicy DestVolReclaimPolicy `json:"destVolReclaimPolicy"`

	// VolumeNamespace is the namespace of the PVCs in this replication group.
	// When empty, PVCs are looked up in this VastStorageClassReplication's
	// namespace.
	// +optional
	VolumeNamespace string `json:"volumeNamespace,omitempty"`
}

// EffectiveSyncIntervalSeconds returns the sync interval in seconds.
// If SyncIntervalSeconds is explicitly set (> 0) it is returned as-is.
// Otherwise the interval is derived from the "every" field of the first
// protectionPolicyTemplate entry.
func (s *VastStorageClassReplicationSpec) EffectiveSyncIntervalSeconds() (int64, error) {
	if s.SyncIntervalSeconds > 0 {
		return s.SyncIntervalSeconds, nil
	}
	if len(s.ProtectionPolicyTemplate.Params) == 0 {
		return 0, fmt.Errorf("syncIntervalSeconds not set and protectionPolicyTemplate has no params")
	}
	return ParseEveryToSeconds(s.ProtectionPolicyTemplate.Params[0].Every)
}

// AllStorageClasses returns every unique StorageClass name in the replication
// group, derived from the ProtectionTopology entries and sorted alphabetically.
func (s *VastStorageClassReplicationSpec) AllStorageClasses() []string {
	seen := make(map[string]struct{}, len(s.ProtectionTopology)*2)
	for _, t := range s.ProtectionTopology {
		seen[t.Source] = struct{}{}
		seen[t.Destination] = struct{}{}
	}
	result := make([]string, 0, len(seen))
	for sc := range seen {
		result = append(result, sc)
	}
	sort.Strings(result)
	return result
}

// AllStorageClassesPrimaryFirst returns the same set as AllStorageClasses but
// with PrimaryStorageClass guaranteed to be the first element.  Use this when
// creation order matters: the primary VGR and its downstream VRC must exist
// before secondary VRCs reconcile so they can find the source PVCs in the
// constellation and create the mirror PVCs.
func (s *VastStorageClassReplicationSpec) AllStorageClassesPrimaryFirst() []string {
	scs := s.AllStorageClasses()
	sort.Slice(scs, func(i, j int) bool {
		if scs[i] == s.PrimaryStorageClass {
			return true
		}
		if scs[j] == s.PrimaryStorageClass {
			return false
		}
		return scs[i] < scs[j]
	})
	return scs
}

// TargetsFor returns all ProtectionTopology entries that involve the given
// StorageClass, oriented so that scName is always Source (the originating side).
func (s *VastStorageClassReplicationSpec) TargetsFor(scName string) []ReplicationTarget {
	var out []ReplicationTarget
	for _, t := range s.ProtectionTopology {
		switch scName {
		case t.Source:
			out = append(out, t)
		case t.Destination:
			out = append(out, ReplicationTarget{
				Source:      t.Destination,
				Destination: t.Source,
				PeerName:    t.PeerName,
			})
		}
	}
	return out
}

// VastStorageClassReplicationStatus defines the observed state of VastStorageClassReplication.
type VastStorageClassReplicationStatus struct {
	// LastFailoverType is the most recent failover type that was applied.
	// +optional
	LastFailoverType FailoverAction `json:"lastFailoverType,omitempty"`

	// CurrentPrimaryStorageClass is the StorageClass that is currently primary
	// (may differ from spec.primaryStorageClass while an action is in progress).
	// +optional
	CurrentPrimaryStorageClass string `json:"currentPrimaryStorageClass,omitempty"`

	// StorageClassesPreview is a human-readable summary of all StorageClasses
	// (primary + all target SCs), formatted for the kubectl printcolumn.
	// +optional
	StorageClassesPreview string `json:"storageClassesPreview,omitempty"`

	// PpathDirMapping maps every StorageClass name in the constellation to its
	// predicted ppath source directory.  For block StorageClasses the value is
	// the subsystem path joined with volume_group; for file StorageClasses it
	// is the root_export parameter value.  For subsystem-level block VSCR,
	// secondaries default to the primary path unless overridden by
	// protectionTopology[].targetExportedDir.  Populated once on the first
	// reconcile and treated as immutable thereafter.
	// +optional
	PpathDirMapping map[string]string `json:"ppathDirMapping,omitempty"`

	// TenantMapping maps every StorageClass name in the constellation to its
	// resolved VAST tenant (from SC tenant_name, subsystem view, or
	// view_policy).  Populated once on the first reconcile and treated as
	// immutable thereafter.  Reused for policy/ppath/stream creates so
	// ResolveTenant is not called again; also surfaces local/remote tenants
	// in kubectl describe / vastrep status.
	// +optional
	TenantMapping map[string]TenantInfo `json:"tenantMapping,omitempty"`

	// PpathName is the VAST protected-path name created by the controller on
	// the primary site.  ONE ppath is created per VSCR; additional policies are
	// added as ReplicationStream objects on that same ppath.  Populated only
	// after the ppath has reached a stable role (SOURCE, DESTINATION, or
	// STANDALONE).  Passed to the CSI plugin via the VRC/VGRC
	// vastdata.com/ppath-name parameter so the plugin can look it up directly
	// without creating a ppath of its own.  SOURCE ↔ DESTINATION switching is
	// the CSI plugin's responsibility.
	// +optional
	PpathName string `json:"ppathName,omitempty"`

	// SyncStatus reflects whether replication for spec.primaryStorageClass has
	// completed its desired state.  "Completed" means the VolumeGroupReplication
	// for the primary StorageClass reports State=Primary; "InProgress" means
	// the transition is still ongoing.
	// +optional
	SyncStatus string `json:"syncStatus,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:scope=Namespaced,shortName=vscr
// +kubebuilder:printcolumn:name="Storage Classes",type=string,JSONPath=`.status.storageClassesPreview`
// +kubebuilder:printcolumn:name="Primary SC",type=string,JSONPath=`.spec.primaryStorageClass`
// +kubebuilder:printcolumn:name="Failover Type",type=string,JSONPath=`.spec.failoverType`
// +kubebuilder:printcolumn:name="Current Primary",type=string,JSONPath=`.status.currentPrimaryStorageClass`
// +kubebuilder:printcolumn:name="Sync Status",type=string,JSONPath=`.status.syncStatus`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// VastStorageClassReplication declares a replication group across multiple
// StorageClasses.  The operator creates one NATIVE_REPLICATION ProtectionPolicy
// per directed link (using the pre-existing ReplicationPeer specified in each
// link) and manages the VAST protected path and replication streams.
type VastStorageClassReplication struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   VastStorageClassReplicationSpec   `json:"spec,omitempty"`
	Status VastStorageClassReplicationStatus `json:"status,omitempty"`
}

// PVCNamespace returns the namespace of the PVCs in this replication group.
// Empty VolumeNamespace means this VastStorageClassReplication's own namespace.
func (v *VastStorageClassReplication) PVCNamespace() string {
	if ns := strings.TrimSpace(v.Spec.VolumeNamespace); ns != "" {
		return ns
	}
	return v.Namespace
}

// +kubebuilder:object:root=true

// VastStorageClassReplicationList contains a list of VastStorageClassReplication.
type VastStorageClassReplicationList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []VastStorageClassReplication `json:"items"`
}

// Validate checks that the spec is internally consistent.
func (s *VastStorageClassReplicationSpec) Validate() error {
	if s.PrimaryStorageClass == "" {
		return fmt.Errorf("primaryStorageClass must not be empty")
	}
	if len(s.ProtectionTopology) == 0 {
		return fmt.Errorf("protectionTopology must contain at least one entry")
	}

	if err := s.ProtectionPolicyTemplate.Validate(); err != nil {
		return err
	}

	if s.PVCRemap && !s.SyncPVCPV {
		return fmt.Errorf(
			"pvcRemap cannot be true when syncPVCPV is false: PVC remap needs mirror PVC/PV pairs on secondaries; set syncPVCPV to true or disable pvcRemap",
		)
	}

	// Build the SC set from the topology and validate each entry.
	type unorderedPair struct{ lo, hi string }
	normPair := func(a, b string) unorderedPair {
		if a <= b {
			return unorderedPair{a, b}
		}
		return unorderedPair{b, a}
	}
	scSet := make(map[string]struct{}, len(s.ProtectionTopology)*2)
	seenPairs := make(map[unorderedPair]struct{}, len(s.ProtectionTopology))
	for i, t := range s.ProtectionTopology {
		if t.Source == "" {
			return fmt.Errorf("protectionTopology[%d].source must not be empty", i)
		}
		if t.Destination == "" {
			return fmt.Errorf("protectionTopology[%d].destination must not be empty", i)
		}
		if t.Source == t.Destination {
			return fmt.Errorf("protectionTopology[%d]: source and destination must be different (%q)", i, t.Source)
		}
		p := normPair(t.Source, t.Destination)
		if _, dup := seenPairs[p]; dup {
			return fmt.Errorf("protectionTopology[%d]: duplicate entry between %q and %q", i, t.Source, t.Destination)
		}
		seenPairs[p] = struct{}{}
		scSet[t.Source] = struct{}{}
		scSet[t.Destination] = struct{}{}
	}

	// Primary must be one of the clusters in the topology.
	if _, ok := scSet[s.PrimaryStorageClass]; !ok {
		return fmt.Errorf("primaryStorageClass %q must appear in protectionTopology", s.PrimaryStorageClass)
	}

	return nil
}

func init() {
	SchemeBuilder.Register(&VastStorageClassReplication{}, &VastStorageClassReplicationList{})
}
