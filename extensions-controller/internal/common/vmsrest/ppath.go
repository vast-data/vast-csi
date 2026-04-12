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
func GetPpath(
	rest *vast_client.TypedVMSRest,
	name string,
) (*typed.ProtectedPathDetailsModel, error) {
	ppath, err := rest.ProtectedPaths.Get(&typed.ProtectedPathSearchParams{
		RawData: vast_client.Params{
			"name":   name,
			"fields": ppathFields,
		},
	})
	if err != nil {
		return nil, fmt.Errorf("failed to get protected path %q: %w", name, err)
	}
	return ppath, nil
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

// AddReplicationStream adds one outbound replication stream to an existing
// protected path unconditionally.  Callers are responsible for ensuring the
// stream does not already exist before calling this function.
func AddReplicationStream(
	rest *vast_client.TypedVMSRest,
	streamName string,
	ppathId int64,
	sourceDir string,
	pair ReplicationLink,
) error {
	remoteTenant, err := ResolveTenantFromVipPool(pair.Edge.RestB, pair.Edge.SCB)
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
	if _, err := rest.Untyped.ProtectedPaths.ProtectedPathAddStream_PATCH(ppathId, params); err != nil {
		return fmt.Errorf("failed to add replication stream %q: %w", streamName, err)
	}
	return nil
}

// EnsurePpath idempotently creates the VAST protected path for the primary
// cluster and submits all outbound streams (one per ReplicationLink).
//
// VAST replication model:
//   - ONE ppath per source directory, named ownerName.
//   - pairs[0] is embedded in the ppath at creation time (its stream is
//     auto-named by VAST).  pairs[1:] are added as explicit streams via
//     add_stream after the initial ppath is active.
//
// This function must only be called for the PRIMARY cluster.  For non-primary
// clusters whose ppaths are auto-mirrored by VAST, use EnsurePpathStreams.
func EnsurePpath(
	rest *vast_client.TypedVMSRest,
	ownerName string,
	sourceDir string,
	pairs []ReplicationLink,
) (ppathName string, err error) {
	if len(pairs) == 0 {
		return "", fmt.Errorf("EnsurePpath requires at least one ReplicationLink (primary cluster must have at least one replication target)")
	}

	var ppathObj typed.ProtectedPathDetailsModel
	record, err := rest.Untyped.ProtectedPaths.Get(core.Params{
		"name":   ownerName,
		"fields": ppathFields,
	})
	if err != nil && !vast_client.IsNotFoundErr(err) {
		return "", fmt.Errorf("failed to check if protected path exists: %w", err)
	}
	if err != nil {
		// ppath does not exist yet — create it using the first policy as the
		// initial embedded stream.
		first := pairs[0]
		localTenant, err := ResolveTenantFromVipPool(first.Edge.RestA, first.Edge.SCA)
		if err != nil {
			return "", fmt.Errorf("SC %s: failed to resolve local tenant: %w", first.Edge.SideA, err)
		}
		remoteTenant, err := ResolveTenantFromVipPool(first.Edge.RestB, first.Edge.SCB)
		if err != nil {
			return "", fmt.Errorf("SC %s: failed to resolve remote tenant: %w", first.Edge.SideB, err)
		}
		ppathBody := core.Params{
			"name":                 ownerName,
			"source_dir":           sourceDir,
			"target_exported_dir":  sourceDir,
			"tenant_id":            localTenant.Id,
			"remote_tenant_guid":   remoteTenant.Guid,
			"protection_policy_id": strconv.FormatInt(first.PolicyId, 10),
			"capabilities":         ppathCapabilities,
			"enabled":              true,
		}
		record, err = rest.Untyped.ProtectedPaths.Create(ppathBody)
		if err != nil {
			return "", err
		}
		// If there are additional streams to add (pairs[1:]), return a short
		// retryable error so the ppath can finish initializing before we call
		// add_stream on the next reconcile.
		if len(pairs) > 1 {
			return "", cerrors.NewRetryAfterError(
				fmt.Errorf("protected path %q was just created, waiting for initialization before adding streams", ownerName),
				5*time.Second,
			)
		}
		return record.RecordName(), nil
	}

	if err := record.Fill(&ppathObj); err != nil {
		return "", fmt.Errorf("failed to decode protected path response: %w", err)
	}
	ppathName = ppathObj.Name
	ppathId := ppathObj.Id

	if ppathObj.FailureReason != "" {
		return ppathName, fmt.Errorf("protected path %q has failed: %s", ppathName, ppathObj.FailureReason)
	}

	// Submit all outbound streams.
	streams := ppathStreams(record)
	streamNames := ppathStreamNameSet(streams)

	for _, pair := range pairs[1:] {
		streamName := truncateName(ownerName + "-" + pair.LocalPeerName + "-" + pair.RemotePeerName)
		if streamNames.Has(streamName) {
			continue
		}
		if err := AddReplicationStream(rest, streamName, ppathId, sourceDir, pair); err != nil {
			return ppathName, err
		}
		return ppathName, cerrors.NewRetryAfterError(
			fmt.Errorf("added stream %q to protected path %q, waiting before adding next stream", streamName, ppathName),
			3*time.Second,
		)
	}

	return ppathName, nil
}

// EnsurePpathStreams submits all streams in pairs to an already-existing
// protected path on a non-primary cluster.
//
// Returns nil when all streams have been submitted.
// Returns a cerrors.RetryAfterError (30 s) when the ppath has not yet been
// mirrored to this cluster by VAST.
// Returns a hard error on permanent failures.
func EnsurePpathStreams(
	rest *vast_client.TypedVMSRest,
	ppathName string,
	sourceDir string,
	pairs []ReplicationLink,
) error {
	record, err := rest.Untyped.ProtectedPaths.Get(core.Params{
		"name":   ppathName,
		"fields": ppathFields,
	})
	if err != nil {
		if core.ExpectStatusCodes(err, http.StatusNotFound) {
			return cerrors.NewRetryAfterError(
				fmt.Errorf("protected path %q not yet mirrored to this cluster", ppathName),
				30*time.Second,
			)
		}
		return fmt.Errorf("failed to get protected path %q: %w", ppathName, err)
	}
	var ppathObj typed.ProtectedPathDetailsModel
	if err := record.Fill(&ppathObj); err != nil {
		return fmt.Errorf("failed to decode protected path %q: %w", ppathName, err)
	}

	// Only bail on a permanent failure; transient states are fine for add_stream.
	if ppathObj.FailureReason != "" {
		return fmt.Errorf("protected path %q has failed: %s", ppathName, ppathObj.FailureReason)
	}

	existingStreams := ppathStreamNameSet(ppathStreams(record))
	ppathId := ppathObj.Id
	for _, pair := range pairs {
		streamName := truncateName(ppathName + "-" + pair.LocalPeerName + "-" + pair.RemotePeerName)
		if existingStreams.Has(streamName) {
			continue
		}
		if err := AddReplicationStream(rest, streamName, ppathId, sourceDir, pair); err != nil {
			return err
		}
	}

	return nil
}

// EnsureConstellationPpath orchestrates the full replication topology for a
// constellation of clusters.  With clusters A (primary), B, C, D the
// ppath and streams are established in this order:
//
//	A's ppath created  — A->B embedded at creation time (first pair)
//	A→C               — extra stream added to A's ppath
//	A→D               — extra stream added to A's ppath
//	B→C               — extra stream added to B's auto-mirrored ppath
//	B→D               — extra stream added to B's auto-mirrored ppath
//	C→D               — extra stream added to C's auto-mirrored ppath
//
// The ppath is created ONLY ONCE on the primary cluster (Step 1), using the
// first ReplicationLink as the embedded stream.  VAST automatically mirrors
// the ppath to every destination cluster (B, C, D).  Step 2 then adds
// cross-replica outbound streams to those mirrored ppaths — it never creates
// a ppath on a non-primary cluster.
//
// All operations are idempotent — safe to call on every reconcile.
func EnsureConstellationPpath(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	pairs map[string][]ReplicationLink,
	primarySC string,
	ownerName string,
	sourceDir string,
) (ppathName string, err error) {
	// create the ppath on the primary cluster.
	ppathName, err = EnsurePpath(
		restByStorageClass[primarySC], ownerName, sourceDir, pairs[primarySC],
	)
	if err != nil {
		return "", fmt.Errorf("primary ppath: %w", err)
	}

	// for each non-primary cluster, verify that VAST has mirrored the
	// ppath and submit any cross-replica outbound streams.
	// policyPairs[sc] may be empty (no cross-replica streams for that cluster)
	// or non-empty (e.g. B→C, B→D for cluster B).
	// NOTE: this loop runs regardless of whether primary streams have finished
	// joining — secondary standby streams (B→C etc.) must be submitted while
	// primary streams may still be in "Waiting for a standby stream" state.
	for sc, rest := range restByStorageClass {
		if sc == primarySC {
			continue
		}
		if err = EnsurePpathStreams(rest, ownerName, sourceDir, pairs[sc]); err != nil {
			return ppathName, fmt.Errorf("SC %s: %w", sc, err)
		}
	}

	return ppathName, nil
}
