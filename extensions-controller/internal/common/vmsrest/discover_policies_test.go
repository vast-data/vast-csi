package vmsrest

import (
	"testing"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

func TestProtectionPolicyNamesByStorageClass_mesh(t *testing.T) {
	topology := []vastv1alpha1.ReplicationTarget{
		{Source: "vastdata-filesystem", Destination: "vastdata-filesystem2", PeerName: "clusterA-clusterB-peer"},
		{Source: "vastdata-filesystem", Destination: "vastdata-filesystem3", PeerName: "clusterA-clusterC-peer"},
		{Source: "vastdata-filesystem2", Destination: "vastdata-filesystem3", PeerName: "clusterB-clusterC-peer"},
	}

	tests := []struct {
		sc       string
		primary  string
		expected []string
	}{
		{
			sc: "vastdata-filesystem",
			expected: []string{
				"app-replication1-clusterA-clusterB-peer",
				"app-replication1-clusterA-clusterC-peer",
			},
		},
		{
			sc: "vastdata-filesystem2",
			expected: []string{
				"app-replication1-clusterA-clusterB-peer",
				"app-replication1-clusterB-clusterC-peer",
			},
		},
		{
			sc: "vastdata-filesystem3",
			expected: []string{
				"app-replication1-clusterA-clusterC-peer",
				"app-replication1-clusterB-clusterC-peer",
			},
		},
	}

	for _, tc := range tests {
		got := ProtectionPolicyNamesByStorageClass("app-replication1", tc.primary, topology)[tc.sc]
		if len(got) != len(tc.expected) {
			t.Fatalf("sc %q: got %v, want %v", tc.sc, got, tc.expected)
		}
		for i := range got {
			if got[i] != tc.expected[i] {
				t.Fatalf("sc %q: got %v, want %v", tc.sc, got, tc.expected)
			}
		}
	}
}

func TestProtectionPolicyNamesByStorageClass_fourSiteMesh(t *testing.T) {
	topology := []vastv1alpha1.ReplicationTarget{
		{Source: "sc-a", Destination: "sc-b", PeerName: "peer-ab"},
		{Source: "sc-a", Destination: "sc-c", PeerName: "peer-ac"},
		{Source: "sc-a", Destination: "sc-d", PeerName: "peer-ad"},
		{Source: "sc-b", Destination: "sc-c", PeerName: "peer-bc"},
		{Source: "sc-b", Destination: "sc-d", PeerName: "peer-bd"},
		{Source: "sc-c", Destination: "sc-d", PeerName: "peer-cd"},
	}
	bySC := ProtectionPolicyNamesByStorageClass("repl", "sc-a", topology)

	want := map[string][]string{
		"sc-a": {"repl-peer-ab", "repl-peer-ac", "repl-peer-ad"},
		"sc-b": {"repl-peer-ab", "repl-peer-bc", "repl-peer-bd"},
		"sc-c": {"repl-peer-ac", "repl-peer-bc", "repl-peer-cd"},
		"sc-d": {"repl-peer-ad", "repl-peer-bd", "repl-peer-cd"},
	}
	for sc, expected := range want {
		got := bySC[sc]
		if len(got) != len(expected) {
			t.Fatalf("sc %q: got %v (%d), want %v (%d)", sc, got, len(got), expected, len(expected))
		}
		for i := range expected {
			if got[i] != expected[i] {
				t.Fatalf("sc %q: got %v, want %v", sc, got, expected)
			}
		}
	}
}

func TestProtectionPolicyNamesByStorageClass_primaryIsDestination(t *testing.T) {
	topology := []vastv1alpha1.ReplicationTarget{
		{Source: "vastdata-filesystem2", Destination: "vastdata-filesystem", PeerName: "clusterA-clusterB-peer"},
	}
	got := ProtectionPolicyNamesByStorageClass("app-replication1", "vastdata-filesystem", topology)["vastdata-filesystem"]
	want := []string{"app-replication1-clusterA-clusterB-peer"}
	if len(got) != 1 || got[0] != want[0] {
		t.Fatalf("got %v, want %v", got, want)
	}
}
