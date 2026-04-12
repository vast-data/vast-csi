package vmsrest

import (
	"fmt"
	"sort"
	"strings"

	vast_client "github.com/vast-data/go-vast-client"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

// ResolvePeerName ensures t.PeerName is set by verifying or discovering the
// shared VAST ReplicationPeer between the two clusters.
//
//   - If t.PeerName is already set, it is verified to exist on both clusters.
//   - If t.PeerName is empty, all peer names from both clusters are listed and
//     their intersection is computed.  Exactly one shared name is required; it
//     is written back to t.PeerName.  Zero or multiple shared peers is an error.
func ResolvePeerName(t *vastv1alpha1.ReplicationTarget, restSrc, restDst *vast_client.TypedVMSRest) error {
	srcPeers, err := restSrc.ReplicationPeers.List(nil)
	if err != nil {
		return fmt.Errorf("list ReplicationPeers on source %q: %w", t.Source, err)
	}
	dstPeers, err := restDst.ReplicationPeers.List(nil)
	if err != nil {
		return fmt.Errorf("list ReplicationPeers on destination %q: %w", t.Destination, err)
	}

	// Build source-side name set, then collect names present on both sides.
	srcSet := make(map[string]struct{}, len(srcPeers))
	for _, p := range srcPeers {
		srcSet[p.Name] = struct{}{}
	}
	var shared []string
	for _, p := range dstPeers {
		if _, ok := srcSet[p.Name]; ok {
			shared = append(shared, p.Name)
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
			"no shared ReplicationPeer between %q and %q; ",
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
