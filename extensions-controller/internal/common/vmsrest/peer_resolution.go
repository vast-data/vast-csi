package vmsrest

import (
	"fmt"
	"sort"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/go-vast-client/resources/typed/expr"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	cerrors "github.com/vast-data/vast-csi/extensions-controller/internal/common/errors"
)

const (
	// peerDiscoveryFields is the minimal field set used to compute the shared
	// peer name between two clusters during auto-discovery.
	peerDiscoveryFields = "name"
	// peerNameFields is the full detail set fetched for topology peers only.
	peerNameFields = "name,status,health,state"
)

// PeerNamesBySC maps StorageClass name -> set of ReplicationPeer names visible
// on that cluster.  Built once by BuildPeerNamesBySC and shared across all
// ResolvePeerName calls so each cluster is queried exactly once.
type PeerNamesBySC map[string]map[string]struct{}

// ResolveAndFetchTopologyPeers resolves peerName on every protectionTopology
// entry (auto-discovery or explicit verification) and then fetches full peer
// detail for topology participants only.  Unrelated ReplicationPeers configured
// on the same cluster are never queried.
func ResolveAndFetchTopologyPeers(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	topology []vastv1alpha1.ReplicationTarget,
) error {
	peersBySC, err := BuildPeerNamesBySC(restByStorageClass, topology)
	if err != nil {
		return err
	}
	for i := range topology {
		if err := ResolvePeerName(&topology[i], peersBySC); err != nil {
			return cerrors.NewValidationError("protectionTopology[%d]: %v", i, err)
		}
	}
	return FetchTopologyPeers(restByStorageClass, topology)
}

// BuildPeerNamesBySC fetches the ReplicationPeer name list from every cluster
// in restByStorageClass exactly once and returns an index keyed by StorageClass
// name.  Callers pass the result to ResolvePeerName to avoid redundant API
// calls when iterating over multiple topology entries.
//
// Query scope depends on the topology:
//   - Explicit peerName on every edge involving the StorageClass: name__in filter.
//   - Any auto-discovery edge involving the StorageClass: full name list only
//     (status is fetched later for resolved topology peers).
func BuildPeerNamesBySC(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	topology []vastv1alpha1.ReplicationTarget,
) (PeerNamesBySC, error) {
	result := make(PeerNamesBySC, len(restByStorageClass))
	for scName, rest := range restByStorageClass {
		params := &typed.ReplicationPeersSearchParams{
			RawData: vast_client.Params{"fields": peerDiscoveryFields},
		}
		if !storageClassNeedsPeerDiscovery(scName, topology) {
			if peerNames := explicitPeerNamesForSC(scName, topology); len(peerNames) > 0 {
				params.Name = expr.Str.In(peerNames...)
			}
		}
		peers, err := rest.ReplicationPeers.List(params)
		if err != nil {
			return nil, fmt.Errorf("list ReplicationPeers on %q: %w", scName, err)
		}
		names := make(map[string]struct{}, len(peers))
		for _, p := range peers {
			names[p.Name] = struct{}{}
		}
		result[scName] = names
	}
	return result, nil
}

// FetchTopologyPeers loads status, health, and state for ReplicationPeers that
// participate in protectionTopology.
func FetchTopologyPeers(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	topology []vastv1alpha1.ReplicationTarget,
) error {
	for scName, peerNames := range topologyPeerNamesBySC(topology) {
		rest, ok := restByStorageClass[scName]
		if !ok {
			return fmt.Errorf("no REST client for StorageClass %q", scName)
		}
		if _, err := rest.ReplicationPeers.List(&typed.ReplicationPeersSearchParams{
			Name:    expr.Str.In(peerNames...),
			RawData: vast_client.Params{"fields": peerNameFields},
		}); err != nil {
			return fmt.Errorf("fetch topology ReplicationPeers on %q: %w", scName, err)
		}
	}
	return nil
}

// storageClassNeedsPeerDiscovery reports whether scName participates in a
// topology edge that still requires auto-discovery (empty peerName).
func storageClassNeedsPeerDiscovery(scName string, topology []vastv1alpha1.ReplicationTarget) bool {
	for _, t := range topology {
		if t.PeerName != "" {
			continue
		}
		if t.Source == scName || t.Destination == scName {
			return true
		}
	}
	return false
}

// explicitPeerNamesForSC returns the distinct non-empty peerName values from
// topology edges that involve scName.
func explicitPeerNamesForSC(scName string, topology []vastv1alpha1.ReplicationTarget) []string {
	seen := make(map[string]struct{})
	for _, t := range topology {
		if t.PeerName == "" {
			continue
		}
		if t.Source != scName && t.Destination != scName {
			continue
		}
		seen[t.PeerName] = struct{}{}
	}
	names := make([]string, 0, len(seen))
	for name := range seen {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

func topologyPeerNamesBySC(topology []vastv1alpha1.ReplicationTarget) map[string][]string {
	seen := make(map[string]map[string]struct{})
	for _, t := range topology {
		if t.PeerName == "" {
			continue
		}
		for _, scName := range []string{t.Source, t.Destination} {
			if seen[scName] == nil {
				seen[scName] = make(map[string]struct{})
			}
			seen[scName][t.PeerName] = struct{}{}
		}
	}
	result := make(map[string][]string, len(seen))
	for scName, names := range seen {
		peerNames := make([]string, 0, len(names))
		for name := range names {
			peerNames = append(peerNames, name)
		}
		sort.Strings(peerNames)
		result[scName] = peerNames
	}
	return result
}

// ResolvePeerName ensures t.PeerName is set by verifying or discovering the
// shared VAST ReplicationPeer between the two clusters using a pre-built peer
// index.  VAST allows at most one ReplicationPeer between any two clusters, so
// auto-discovery expects exactly one name in the intersection.
//
//   - If t.PeerName is already set, it is verified to exist on both clusters.
//   - If t.PeerName is empty, the intersection of peer names on both clusters
//     is computed.  Exactly one shared name is required; it is written back to
//     t.PeerName.  Zero or multiple shared peers is an error.
func ResolvePeerName(t *vastv1alpha1.ReplicationTarget, peersBySC PeerNamesBySC) error {
	srcNames, ok := peersBySC[t.Source]
	if !ok {
		return fmt.Errorf("no peer data for StorageClass %q (source)", t.Source)
	}
	dstNames, ok := peersBySC[t.Destination]
	if !ok {
		return fmt.Errorf("no peer data for StorageClass %q (destination)", t.Destination)
	}

	// Collect names present on both sides.
	var shared []string
	for name := range srcNames {
		if _, ok := dstNames[name]; ok {
			shared = append(shared, name)
		}
	}
	sort.Strings(shared) // deterministic error messages

	if t.PeerName != "" {
		for _, name := range shared {
			if name == t.PeerName {
				return nil
			}
		}
		return fmt.Errorf(
			"peerName %q does not exist on both %q and %q (shared peers: [%s])",
			t.PeerName, t.Source, t.Destination, strings.Join(shared, ", "))
	}

	// Auto-discover: exactly one shared peer is required.
	switch len(shared) {
	case 0:
		return fmt.Errorf(
			"no shared ReplicationPeer between %q and %q",
			t.Source, t.Destination)
	case 1:
		t.PeerName = shared[0]
		return nil
	default:
		return fmt.Errorf(
			"multiple shared ReplicationPeers between %q and %q (%s); "+
				"set peerName explicitly to disambiguate",
			t.Source, t.Destination, strings.Join(shared, ", "))
	}
}
