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
	"strings"
)

// ReplicationTarget describes one undirected replication edge in the mesh.
//
// Source and Destination are the two StorageClasses (clusters) connected by
// this entry.  PeerName is the name of the VAST ReplicationPeer that must
// exist under the same name on both clusters (each pointing to the other).
// The operator creates one NATIVE_REPLICATION ProtectionPolicy on each side.
//
// PeerName is optional: if omitted the operator discovers it automatically by
// finding the single peer name shared by both clusters.  If multiple peers are
// shared between the clusters, PeerName must be set explicitly to disambiguate.
type ReplicationTarget struct {
	// Source is the StorageClass of one cluster in this replication pair.
	// +kubebuilder:validation:Required
	Source string `json:"source"`

	// Destination is the StorageClass of the other cluster in this pair.
	// +kubebuilder:validation:Required
	Destination string `json:"destination"`

	// PeerName is the name of the VAST ReplicationPeer that exists on both
	// clusters and establishes bidirectional connectivity between them.
	// Users must pre-create this peer on both VAST management servers.
	// If omitted, the operator discovers it automatically; an error is returned
	// if zero or more than one shared peer is found.
	// +optional
	PeerName string `json:"peerName,omitempty"`

	// TargetExportedDir is an optional absolute path on the Destination
	// StorageClass for subsystem-level block VSCR only.  Use when the dest
	// subsystem root differs from the source; ignored for all other
	// replication types.
	// +optional
	// +kubebuilder:validation:XValidation:rule="self == oldSelf",message="targetExportedDir is immutable"
	TargetExportedDir string `json:"targetExportedDir,omitempty"`
}

// Validate checks structural consistency of t.
// It does NOT perform any network I/O; peer resolution is handled by
// vmsrest.ResolvePeerName after REST clients have been established.
func (t *ReplicationTarget) Validate() error {
	if t.Source == "" {
		return fmt.Errorf("source must not be empty")
	}
	if t.Destination == "" {
		return fmt.Errorf("destination must not be empty")
	}
	if t.Source == t.Destination {
		return fmt.Errorf("source and destination must be different (both are %q)", t.Source)
	}
	if t.TargetExportedDir != "" && !strings.HasPrefix(t.TargetExportedDir, "/") {
		return fmt.Errorf("targetExportedDir must be an absolute path (got %q)", t.TargetExportedDir)
	}
	return nil
}
