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
	// Every is the replication interval.
	// Time units: s/S=seconds, m=minutes (lowercase only; M=months),
	// h/H=hours, d/D=days, w/W=weeks, M=months(30d), y/Y=years.
	// Examples: "30s", "15m", "1h", "1d", "1w", "1M", "1y".
	// +kubebuilder:validation:Required
	Every string `json:"every"`

	// KeepLocal is how long local snapshots are retained.
	// Same time units as Every. E.g. "2d", "1w", "1M".
	// +optional
	KeepLocal string `json:"keepLocal,omitempty"`

	// KeepRemote is how long remote snapshots are retained.
	// Same time units as Every. E.g. "7d", "4w", "1M".
	// +optional
	KeepRemote string `json:"keepRemote,omitempty"`

	// StartAt is an optional time at which the first snapshot is taken.
	// Accepted formats: "YYYY-MM-DD HH:MM:SS", "HH:MM", or RFC-3339.
	// Example: "2025-01-01 02:00:00".
	// +optional
	StartAt string `json:"startAt,omitempty"`
}

// vastDurationRe matches VAST schedule durations: one or more digits followed
// by a single unit letter.
//
// Units (case-insensitive except m vs M):
//
//	s / S  – seconds
//	m      – minutes (lowercase only; uppercase M = months)
//	h / H  – hours
//	d / D  – days
//	w / W  – weeks
//	M      – months (= 30 days)
//	y / Y  – years  (= 365 days)
var vastDurationRe = regexp.MustCompile(`^\d+[sSmMhHdDwWyY]$`)

// Validate checks that all fields of f are syntactically valid.
//
//   - Every:      required; must be a VAST duration (e.g. "30s", "15m", "1h", "1d", "1w", "1M", "1y").
//   - KeepLocal:  optional; if set, must be a VAST duration.
//   - KeepRemote: optional; if set, must be a VAST duration.
//   - StartAt:    optional; if set, must be "YYYY-MM-DD HH:MM:SS", "HH:MM", or RFC-3339.
func (f *ProtectionPolicyFrame) Validate() error {
	if f.Every == "" {
		return fmt.Errorf("every must not be empty")
	}
	if !vastDurationRe.MatchString(f.Every) {
		return fmt.Errorf("every %q is not a valid VAST duration (expected <number><unit>, e.g. \"15m\", \"1h\", \"2d\", \"1w\", \"1M\", \"1y\")", f.Every)
	}
	if f.KeepLocal != "" && !vastDurationRe.MatchString(f.KeepLocal) {
		return fmt.Errorf("keepLocal %q is not a valid VAST duration (expected <number><unit>, e.g. \"2d\", \"1w\")", f.KeepLocal)
	}
	if f.KeepRemote != "" && !vastDurationRe.MatchString(f.KeepRemote) {
		return fmt.Errorf("keepRemote %q is not a valid VAST duration (expected <number><unit>, e.g. \"7d\", \"4w\")", f.KeepRemote)
	}
	if f.StartAt != "" {
		if err := validateStartAt(f.StartAt); err != nil {
			return err
		}
	}
	return nil
}

// validateStartAt accepts "YYYY-MM-DD HH:MM:SS" (VMS native format),
// "HH:MM" bare time, or a full RFC-3339 timestamp.
func validateStartAt(s string) error {
	if _, err := time.Parse("2006-01-02 15:04:05", s); err == nil {
		return nil
	}
	if _, err := time.Parse("15:04", s); err == nil {
		return nil
	}
	if _, err := time.Parse(time.RFC3339, s); err == nil {
		return nil
	}
	return fmt.Errorf("startAt %q must be \"YYYY-MM-DD HH:MM:SS\", \"HH:MM\", or RFC-3339 (e.g. %q, %q, or %q)",
		s, "2025-01-01 02:00:00", "02:00", strings.TrimSuffix(time.Now().UTC().Format(time.RFC3339), "Z")+"Z")
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
