package vmsrest

import (
	"fmt"
	"sort"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

const peerNameFields = "name,status,health,state"

// PeerNamesBySC maps StorageClass name -> set of ReplicationPeer names visible
// on that cluster.  Built once by BuildPeerNamesBySC and shared across all
// ResolvePeerName calls so each cluster is queried exactly once.
type PeerNamesBySC map[string]map[string]struct{}

// BuildPeerNamesBySC fetches the ReplicationPeer name list from every cluster
// in restByStorageClass exactly once and returns an index keyed by StorageClass
// name.  Callers pass the result to ResolvePeerName to avoid redundant API
// calls when iterating over multiple topology entries.
func BuildPeerNamesBySC(restByStorageClass map[string]*vast_client.TypedVMSRest) (PeerNamesBySC, error) {
	result := make(PeerNamesBySC, len(restByStorageClass))
	for scName, rest := range restByStorageClass {
		peers, err := rest.ReplicationPeers.List(&typed.ReplicationPeersSearchParams{
			RawData: vast_client.Params{"fields": peerNameFields},
		})
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

// ResolvePeerName ensures t.PeerName is set by verifying or discovering the
// shared VAST ReplicationPeer between the two clusters using a pre-built peer
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
