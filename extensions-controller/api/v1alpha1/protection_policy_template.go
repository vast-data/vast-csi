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
	"regexp"
	"strings"
	"time"
)

// ProtectionPolicyFrame defines one schedule frame for a VAST ProtectionPolicy.
// It maps directly to the VAST API "frames" array on a ProtectionPolicy object.
type ProtectionPolicyFrame struct {
	// Every is the replication interval, e.g. "15m", "1h", "1d".
	// +kubebuilder:validation:Required
	Every string `json:"every"`

	// KeepLocal is how long local snapshots are retained, e.g. "7d", "1w".
	// +optional
	KeepLocal string `json:"keepLocal,omitempty"`

	// KeepRemote is how long remote snapshots are retained, e.g. "30d".
	// +optional
	KeepRemote string `json:"keepRemote,omitempty"`

	// StartAt is an optional wall-clock time at which the first snapshot is
	// taken, in RFC-3339 format or a bare time like "22:00".
	// +optional
	StartAt string `json:"startAt,omitempty"`
}

// vastDurationRe matches VAST schedule durations: one or more digits followed
// by a single case-insensitive unit letter — M(inutes), H(ours), D(ays), W(eeks).
// Examples: "15M", "1H", "2D", "4W".
var vastDurationRe = regexp.MustCompile(`^\d+[MHDWmhdw]$`)

// Validate checks that all fields of f are syntactically valid.
//
//   - Every:      required; must be a VAST duration (e.g. "15M", "1H", "2D", "1W").
//   - KeepLocal:  optional; if set, must be a VAST duration.
//   - KeepRemote: optional; if set, must be a VAST duration.
//   - StartAt:    optional; if set, must be either "HH:MM" or RFC-3339.
func (f *ProtectionPolicyFrame) Validate() error {
	if f.Every == "" {
		return fmt.Errorf("every must not be empty")
	}
	if !vastDurationRe.MatchString(f.Every) {
		return fmt.Errorf("every %q is not a valid VAST duration (expected <number><unit>, e.g. \"15M\", \"1H\", \"2D\", \"1W\")", f.Every)
	}
	if f.KeepLocal != "" && !vastDurationRe.MatchString(f.KeepLocal) {
		return fmt.Errorf("keepLocal %q is not a valid VAST duration (expected <number><unit>, e.g. \"2D\", \"1W\")", f.KeepLocal)
	}
	if f.KeepRemote != "" && !vastDurationRe.MatchString(f.KeepRemote) {
		return fmt.Errorf("keepRemote %q is not a valid VAST duration (expected <number><unit>, e.g. \"7D\", \"4W\")", f.KeepRemote)
	}
	if f.StartAt != "" {
		if err := validateStartAt(f.StartAt); err != nil {
			return err
		}
	}
	return nil
}

// validateStartAt accepts either "HH:MM" bare time or a full RFC-3339 timestamp.
func validateStartAt(s string) error {
	if _, err := time.Parse("15:04", s); err == nil {
		return nil
	}
	if _, err := time.Parse(time.RFC3339, s); err == nil {
		return nil
	}
	return fmt.Errorf("startAt %q must be \"HH:MM\" or RFC-3339 (e.g. %q or %q)",
		s, "22:00", strings.TrimSuffix(time.Now().UTC().Format(time.RFC3339), "Z")+"Z")
}

// ProtectionPolicyTemplate describes how the operator should create the
// NATIVE_REPLICATION ProtectionPolicy for each entry in the replication mesh.
//
// One policy is created per topology entry side, named
// "{ownerName}-{peerName}".  The VAST snapshot prefix is derived from
// the peer's own peer_name field on the NativeReplicationRemoteTarget.
// Policies are immutable once created.
type ProtectionPolicyTemplate struct {
	// Params defines the replication schedule frames.  At least one is required.
	// +kubebuilder:validation:MinItems=1
	Params []ProtectionPolicyFrame `json:"params"`
}

// Validate checks that the template is internally consistent.
func (t *ProtectionPolicyTemplate) Validate() error {
	if len(t.Params) == 0 {
		return fmt.Errorf("protectionPolicyTemplate.params must contain at least one entry")
	}
	for i := range t.Params {
		if err := t.Params[i].Validate(); err != nil {
			return fmt.Errorf("protectionPolicyTemplate.params[%d]: %w", i, err)
		}
	}
	return nil
}
