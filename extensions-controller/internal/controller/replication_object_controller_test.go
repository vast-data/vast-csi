package controller

import (
	"testing"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

func TestProtectionPolicyNamesForVRC_tertiarySite(t *testing.T) {
	topology := []vastv1alpha1.ReplicationTarget{
		{Source: "vastdata-filesystem", Destination: "vastdata-filesystem2", PeerName: "clusterA-clusterB-peer"},
		{Source: "vastdata-filesystem", Destination: "vastdata-filesystem3", PeerName: "clusterA-clusterC-peer"},
		{Source: "vastdata-filesystem2", Destination: "vastdata-filesystem3", PeerName: "clusterB-clusterC-peer"},
	}

	got, err := protectionPolicyNamesForVRC(
		"app-replication", "vastdata-filesystem", topology, "vastdata-filesystem3",
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{
		"app-replication-clusterA-clusterC-peer",
		"app-replication-clusterB-clusterC-peer",
	}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestProtectionPolicyNamesForVRC_ownedPolicies(t *testing.T) {
	topology := []vastv1alpha1.ReplicationTarget{
		{Source: "vastdata-filesystem", Destination: "vastdata-filesystem2", PeerName: "clusterA-clusterB-peer"},
	}
	got, err := protectionPolicyNamesForVRC(
		"app-replication", "vastdata-filesystem", topology, "vastdata-filesystem",
	)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"app-replication-clusterA-clusterB-peer"}
	if len(got) != 1 || got[0] != want[0] {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestProtectionPolicyNamesForVRC_emptyErrors(t *testing.T) {
	_, err := protectionPolicyNamesForVRC("app-replication", "vastdata-filesystem", nil, "vastdata-filesystem3")
	if err == nil {
		t.Fatal("expected error for missing topology policies")
	}
}
