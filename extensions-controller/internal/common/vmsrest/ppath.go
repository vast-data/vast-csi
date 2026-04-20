package vmsrest

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/core"
	"github.com/vast-data/go-vast-client/resources/typed"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
	"go.uber.org/zap"
	"k8s.io/apimachinery/pkg/util/sets"
)

const (
	ppathCapabilities         = "ASYNC_REPLICATION"
	ppathActiveState          = "active"
	ppathPartiallyActiveState = "partially active"

	// ppathFields is the field projection used for all protected path GET
	// requests in this package, covering state checks, role queries, and
	// stream membership inspection.
	ppathFields = "id,name,state,failure_reason,role,replication_streams"

	// vastNameMaxLen is the maximum number of characters allowed in a VAST
	// object name (enforced by the API for protected paths, streams, etc.).
	vastNameMaxLen = 64

	// Stream state strings returned by the VMS REST API.
	streamStateActive            = "Active"
	streamStateWaitingForStandby = "Waiting for a standby stream"

	// Polling timeouts for state transitions.
	ppathActiveTimeout             = 5 * time.Minute
	ppathActiveSleep               = 15 * time.Second
	streamWaitingForStandbyTimeout = 5 * time.Minute
	streamWaitingForStandbySleep   = 10 * time.Second
	streamActiveTimeout            = 10 * time.Minute
	streamActiveSleep              = 10 * time.Second
	ppathMirrorTimeout             = 2 * time.Minute
	ppathMirrorSleep               = 10 * time.Second
)

// truncateName clips s to vastNameMaxLen characters so VAST API calls never
// fail with a "name too long" 400 error.
func truncateName(s string) string {
	if len(s) <= vastNameMaxLen {
		return s
	}
	return s[:vastNameMaxLen]
}

// ppathStreams extracts the replication streams embedded in a ppath API record
// and returns them as a typed slice.
func ppathStreams(record core.Record) []typed.ReplicationStreamDetailsModel {
	rawStreams, ok := record["replication_streams"].([]any)
	if !ok {
		return nil
	}
	rs := make(core.RecordSet, 0, len(rawStreams))
	for _, s := range rawStreams {
		if m, ok := s.(map[string]any); ok {
			rs = append(rs, core.Record(m))
		}
	}
	var streams []typed.ReplicationStreamDetailsModel
	if err := rs.Fill(&streams); err != nil {
		return nil
	}
	return streams
}

// ppathStreamNameSet builds a set of stream names from a slice returned by
// ppathStreams, for O(1) membership tests.
func ppathStreamNameSet(streams []typed.ReplicationStreamDetailsModel) sets.Set[string] {
	names := sets.New[string]()
	for _, s := range streams {
		if s.Name != "" {
			names.Insert(s.Name)
		}
	}
	return names
}

// checkPpathState reports whether a protected path is ready for use.
//
//   - nil              – state is "active" or "partially active"; ppath is ready.
//   - hard error       – FailureReason is set; the ppath has permanently failed
//     and requeueing will not help.
//   - RetryAfterError  – any other transient state; caller should requeue after
//     the embedded 30 s delay.
func checkPpathState(name, state, failureReason string) error {
	switch strings.ToLower(state) {
	case ppathActiveState, ppathPartiallyActiveState:
		return nil
	}
	if failureReason != "" {
		return fmt.Errorf("protected path %q is not active (state=%q): %s", name, state, failureReason)
	}
	return cerrors.NewRetryAfterError(
		fmt.Errorf("protected path %q is not yet active (state=%q)", name, state),
		30*time.Second,
	)
}

// GetPpath fetches the named protected path.
func GetPpath(rest *vast_client.TypedVMSRest, name string) (*typed.ProtectedPathDetailsModel, error) {
	_, obj, err := getPpathRecord(rest, name)
	return obj, err
}

// IsPpathActive fetches the named protected path and returns nil when it is
// active, a cerrors.RetryAfterError (30 s) when it is in a transient state,
// or a hard error when it has permanently failed or cannot be fetched.
func IsPpathActive(
	rest *vast_client.TypedVMSRest,
	name string,
) error {
	ppath, err := GetPpath(rest, name)
	if err != nil {
		return err
	}
	return checkPpathState(ppath.Name, ppath.State, ppath.FailureReason)
}

// waitForStreamState polls the ppath until the named stream's State field
// matches one of expectedStates.  An empty stream list or a missing stream is
// treated as "not yet ready" (not an error) so the function keeps retrying.
// A non-empty FailureReason on the ppath is treated as a permanent error.
func waitForStreamState(
	rest *vast_client.TypedVMSRest,
	ppathName string,
	streamName string,
	expectedStates []string,
	timeout, sleep time.Duration,
	log *zap.Logger,
) error {
	expected := sets.New(expectedStates...)
	return WaitResource(timeout, sleep,
		fmt.Sprintf("stream %q in ppath %q to reach state %v", streamName, ppathName, expectedStates),
		func() (bool, error) {
			record, err := rest.Untyped.ProtectedPaths.Get(core.Params{
				"name":   ppathName,
				"fields": ppathFields,
			})
			if err != nil {
				if vast_client.IsNotFoundErr(err) {
					return false, nil
				}
				return false, err
			}
			var obj typed.ProtectedPathDetailsModel
			if err := record.Fill(&obj); err != nil {
				return false, err
			}
			if obj.FailureReason != "" {
				return false, fmt.Errorf("ppath %q permanently failed: %s", ppathName, obj.FailureReason)
			}
			for _, s := range ppathStreams(record) {
				if s.Name == streamName {
					if expected.Has(s.State) {
						return true, nil
					}
					log.Info("waiting for stream state transition",
						zap.String("ppath", ppathName),
						zap.String("stream", streamName),
						zap.String("current_state", s.State),
						zap.Strings("expected_states", expectedStates))
					return false, nil
				}
			}
			log.Info("waiting for stream to appear in ppath",
				zap.String("ppath", ppathName),
				zap.String("stream", streamName),
				zap.Strings("expected_states", expectedStates))
			return false, nil
		},
	)
}

// getPpathRecord fetches the ppath by name using the untyped API.
func getPpathRecord(
	rest *vast_client.TypedVMSRest,
	ppathName string,
) (core.Record, *typed.ProtectedPathDetailsModel, error) {
	record, err := rest.Untyped.ProtectedPaths.Get(core.Params{
		"name":   ppathName,
		"fields": ppathFields,
	})
	if err != nil {
		return nil, nil, fmt.Errorf("failed to get protected path %q: %w", ppathName, err)
	}
	var obj typed.ProtectedPathDetailsModel
	if err := record.Fill(&obj); err != nil {
		return nil, nil, fmt.Errorf("failed to decode protected path %q: %w", ppathName, err)
	}
	return record, &obj, nil
}

// waitForPpath blocks until the named ppath appears on this cluster.
func waitForPpath(
	rest *vast_client.TypedVMSRest,
	ppathName string,
	log *zap.Logger,
) (ppathId int64, streams []typed.ReplicationStreamDetailsModel, err error) {
	pollErr := WaitResource(ppathMirrorTimeout, ppathMirrorSleep,
		fmt.Sprintf("ppath %q to appear on cluster", ppathName),
		func() (bool, error) {
			record, obj, ferr := getPpathRecord(rest, ppathName)
			if ferr != nil {
				if core.ExpectStatusCodes(ferr, http.StatusNotFound) {
					log.Info("waiting for ppath to be mirrored to this cluster",
						zap.String("ppath", ppathName))
					return false, nil
				}
				return false, ferr
			}
			ppathId = obj.Id
			streams = ppathStreams(record)
			return true, nil
		},
	)
	return ppathId, streams, pollErr
}

// AddReplicationStream adds one outbound replication stream to an existing
// protected path.  Set isStandby=true for cross-replica (B→C) streams that
// must be added only after the primary cluster's corresponding stream reaches
// "Waiting for a standby stream" state.
func AddReplicationStream(
	rest *vast_client.TypedVMSRest,
	streamName string,
	ppathId int64,
	sourceDir string,
	pair ReplicationLink,
	isStandby bool,
) error {
	remoteTenant, err := ResolveTenant(pair.Edge.RestB, pair.Edge.SCB)
	if err != nil {
		return fmt.Errorf("SC %s: failed to resolve remote tenant: %w", pair.Edge.SideB, err)
	}
	params := core.Params{
		"name":                 streamName,
		"target_exported_dir":  sourceDir,
		"protection_policy_id": pair.PolicyId,
		"remote_tenant_guid":   remoteTenant.Guid,
		"capabilities":         ppathCapabilities,
	}
	if isStandby {
		params["is_standby"] = true
	}
	if _, err := rest.Untyped.ProtectedPaths.ProtectedPathAddStream_PATCH(ppathId, params); err != nil {
		return fmt.Errorf("failed to add replication stream %q: %w", streamName, err)
	}
	return nil
}

// EnsurePpath idempotently creates the VAST protected path for the primary
// cluster with the first (embedded) replication stream, then waits for the
// ppath to become active.
//
// Returns the ppath name and ID once active.  Callers are responsible for
// adding extra streams via EnsureConstellationPpath.
func EnsurePpath(
	rest *vast_client.TypedVMSRest,
	ownerName string,
	sourceDir string,
	first ReplicationLink,
	log *zap.Logger,
) (ppathName string, ppathId int64, err error) {
	record, err := rest.Untyped.ProtectedPaths.Get(core.Params{
		"name":   ownerName,
		"fields": ppathFields,
	})
	if err != nil && !vast_client.IsNotFoundErr(err) {
		return "", 0, fmt.Errorf("failed to check if protected path exists: %w", err)
	}

	if vast_client.IsNotFoundErr(err) {
		localTenant, err := ResolveTenant(first.Edge.RestA, first.Edge.SCA)
		if err != nil {
			return "", 0, fmt.Errorf("SC %s: failed to resolve local tenant: %w", first.Edge.SideA, err)
		}
		remoteTenant, err := ResolveTenant(first.Edge.RestB, first.Edge.SCB)
		if err != nil {
			return "", 0, fmt.Errorf("SC %s: failed to resolve remote tenant: %w", first.Edge.SideB, err)
		}
		record, err = rest.Untyped.ProtectedPaths.Create(core.Params{
			"name":                 ownerName,
			"source_dir":           sourceDir,
			"target_exported_dir":  sourceDir,
			"tenant_id":            localTenant.Id,
			"remote_tenant_guid":   remoteTenant.Guid,
			"protection_policy_id": strconv.FormatInt(first.PolicyId, 10),
			"capabilities":         ppathCapabilities,
			"enabled":              true,
		})
		if err != nil {
			return "", 0, fmt.Errorf("failed to create protected path: %w", err)
		}
		time.Sleep(20 * time.Second)
	}

	// Re-fetch with full field projection to get embedded stream names.
	record, obj, err := getPpathRecord(rest, ownerName)
	if err != nil {
		return "", 0, err
	}
	if obj.FailureReason != "" {
		return obj.Name, obj.Id, fmt.Errorf("protected path %q has failed: %s", obj.Name, obj.FailureReason)
	}

	streams := ppathStreams(record)
	if len(streams) == 0 {
		return obj.Name, obj.Id, fmt.Errorf("ppath %q has no embedded streams after creation", obj.Name)
	}
	firstStreamName := streams[0].Name

	if err := waitForStreamState(
		rest, obj.Name, firstStreamName,
		[]string{streamStateActive},
		ppathActiveTimeout, ppathActiveSleep,
		log,
	); err != nil {
		return obj.Name, obj.Id, fmt.Errorf("ppath %q first stream %q did not become active: %w", obj.Name, firstStreamName, err)
	}
	return obj.Name, obj.Id, nil
}

// EnsureConstellationPpath orchestrates the full replication topology for a
// constellation of clusters.  With clusters A (primary), B, C the ppath and
// streams are established in this strict order:
//
//  1. A's ppath is created with A→B embedded; wait for ppath active.
//  2. For each additional primary target (C, D, …):
//     a. Add A→C (primary stream) to A's ppath.
//     b. Wait for A→C to reach "Waiting for a standby stream".
//     c. On each non-primary cluster whose link targets C (e.g. B): wait for
//     the ppath to be mirrored, then add B→C as a standby stream.
//     d. Wait for A→C to reach "Active".
//
// All stream additions are idempotent — safe to call on every reconcile.
func EnsureConstellationPpath(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	pairs map[string][]ReplicationLink,
	primarySC string,
	ownerName string,
	sourceDir string,
	log *zap.Logger,
) (ppathName string, err error) {
	primaryPairs := pairs[primarySC]
	if len(primaryPairs) == 0 {
		return "", fmt.Errorf("no primary replication links for StorageClass %q", primarySC)
	}
	primaryRest := restByStorageClass[primarySC]

	// Ensure ppath with first embedded stream and wait for active.
	ppathName, ppathId, err := EnsurePpath(primaryRest, ownerName, sourceDir, primaryPairs[0], log)
	if err != nil {
		return ppathName, fmt.Errorf("primary ppath: %w", err)
	}

	// For each additional primary target, interleave primary and
	// standby stream additions with proper state gating.
	for _, primaryPair := range primaryPairs[1:] {
		targetSC := primaryPair.Edge.SideB
		primaryStreamName := truncateName(ownerName + "-" + primaryPair.LocalPeerName + "-" + primaryPair.RemotePeerName)

		// Add the primary stream A→C if not already present.
		{
			record, _, ferr := getPpathRecord(primaryRest, ppathName)
			if ferr != nil {
				return ppathName, fmt.Errorf("primary ppath: %w", ferr)
			}
			if !ppathStreamNameSet(ppathStreams(record)).Has(primaryStreamName) {
				log.Info("adding primary replication stream",
					zap.String("stream", primaryStreamName),
					zap.String("ppath", ppathName),
					zap.String("source_cluster", primaryPair.Edge.SideA),
					zap.String("destination_cluster", primaryPair.Edge.SideB))
				if ferr := AddReplicationStream(primaryRest, primaryStreamName, ppathId, sourceDir, primaryPair, false); ferr != nil {
					return ppathName, fmt.Errorf("add primary stream %q: %w", primaryStreamName, ferr)
				}
				log.Info("primary replication stream added successfully",
					zap.String("stream", primaryStreamName),
					zap.String("ppath", ppathName))
			}
		}

		// Wait for A→C to reach "Waiting for a standby stream" before
		// adding any cross-replica streams that target the same remote.
		if err := waitForStreamState(
			primaryRest, ppathName, primaryStreamName,
			[]string{streamStateWaitingForStandby},
			streamWaitingForStandbyTimeout, streamWaitingForStandbySleep,
			log,
		); err != nil {
			return ppathName, fmt.Errorf("primary stream %q: %w", primaryStreamName, err)
		}

		// Add cross-replica standby streams targeting the same remote SC.
		for sc, crossPairs := range pairs {
			if sc == primarySC {
				continue
			}
			crossRest := restByStorageClass[sc]
			for _, crossPair := range crossPairs {
				if crossPair.Edge.SideB != targetSC {
					continue
				}
				crossStreamName := truncateName(ppathName + "-" + crossPair.LocalPeerName + "-" + crossPair.RemotePeerName)

				crossPpathId, crossStreams, ferr := waitForPpath(crossRest, ppathName, log)
				if ferr != nil {
					return ppathName, fmt.Errorf("SC %s: ppath mirror: %w", sc, ferr)
				}
				if !ppathStreamNameSet(crossStreams).Has(crossStreamName) {
					log.Info("adding standby replication stream",
						zap.String("stream", crossStreamName),
						zap.String("ppath", ppathName),
						zap.String("source_cluster", crossPair.Edge.SideA),
						zap.String("destination_cluster", crossPair.Edge.SideB))
					if ferr := AddReplicationStream(crossRest, crossStreamName, crossPpathId, sourceDir, crossPair, true); ferr != nil {
						return ppathName, fmt.Errorf("SC %s: standby stream %q: %w", sc, crossStreamName, ferr)
					}
					log.Info("standby replication stream added successfully",
						zap.String("stream", crossStreamName),
						zap.String("ppath", ppathName))
				}
			}
		}

		// Wait for A→C to become "Active" before moving to the next target.
		if err := waitForStreamState(
			primaryRest, ppathName, primaryStreamName,
			[]string{streamStateActive},
			streamActiveTimeout, streamActiveSleep,
			log,
		); err != nil {
			return ppathName, fmt.Errorf("primary stream %q: wait for active: %w", primaryStreamName, err)
		}
	}

	// For non-primary clusters that have no cross-replica streams of their own
	// but whose ppath must exist before the reconciler proceeds — verify the
	// mirror is visible.  (pairs[sc] may be empty for leaf clusters.)
	for sc, rest := range restByStorageClass {
		if sc == primarySC {
			continue
		}
		if _, _, ferr := waitForPpath(rest, ppathName, log); ferr != nil {
			return ppathName, fmt.Errorf("SC %s: ppath mirror: %w", sc, ferr)
		}
	}

	return ppathName, nil
}
