package vmsrest

import (
	"context"
	"fmt"
	"time"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/core"
	"github.com/vast-data/go-vast-client/resources/typed"
	"github.com/vast-data/go-vast-client/resources/typed/expr"
	"go.uber.org/zap"

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	k8s_client "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

const (
	// policyMirrorTimeout is how long to wait for VAST to mirror a newly
	// created NATIVE_REPLICATION ProtectionPolicy to the destination cluster.
	policyMirrorTimeout = 60 * time.Second
	policyMirrorSleep   = 5 * time.Second
)

// ReplicationLinkEdge extends ReplicationEdge with resolved tenant identity for
// both sides of the link.  Tenants are taken from status.tenantMapping (populated
// once via ResolveTenant) so policy/ppath/stream creates do not re-query VMS.
type ReplicationLinkEdge struct {
	ReplicationEdge // embedded: SideA, SideB, PeerName
	LocalTenant     vastv1alpha1.TenantInfo
	RemoteTenant    vastv1alpha1.TenantInfo
}

// ReplicationLink carries all fields needed to create or attach a replication
// stream from the local (SideA) cluster to a remote (SideB) cluster.
type ReplicationLink struct {
	PolicyName           string // protection policy name (local)
	PolicyId             int64  // policy ID used as ProtectionPolicyId when creating the ppath/stream
	LocalPeerTargetName  string // Name of the NativeReplicationRemoteTarget on the local (SideA) cluster
	RemotePeerTargetName string // Name of the NativeReplicationRemoteTarget on the remote (SideB) cluster
	LocalPeerName        string // PeerName field of the SideA peer model (remote cluster's id for SideA)
	RemotePeerName       string // PeerName field of the SideB peer model (remote cluster's id for SideB)
	Edge                 ReplicationLinkEdge
}

// ReplicationEdge describes one directed replication edge in the mesh.
// It mirrors vastv1alpha1.ReplicationTarget but lives in this package to avoid
// an import cycle between the vmsrest utility package and the API types.
type ReplicationEdge struct {
	// SideA is the StorageClass of the cluster that originates the replication.
	SideA string
	// SideB is the StorageClass of the destination cluster.
	SideB string
	// PeerName is the name of the VAST ReplicationPeer (NativeReplicationRemoteTarget)
	// on SideA's cluster that points to SideB.
	PeerName string
}

// ReplicationEdgesList is an ordered slice of directed ReplicationEdge values.
type ReplicationEdgesList []ReplicationEdge

// NewReplicationEdgesList converts a ProtectionTopology into a directed edge
// list for DiscoverLinkPolicies.
//
// Each undirected topology entry contributes ONE directed edge.  The edge is
// oriented so that primarySC is always SideA (the policy creator / ppath
// source).  For entries that do not involve primarySC the declared
// source→destination direction is preserved.
func NewReplicationEdgesList(topology []vastv1alpha1.ReplicationTarget, primarySC string) ReplicationEdgesList {
	edges := make(ReplicationEdgesList, 0, len(topology))
	for _, t := range topology {
		if t.Destination == primarySC {
			// Primary is declared as destination — swap so primary is SideA.
			edges = append(edges, ReplicationEdge{SideA: t.Destination, SideB: t.Source, PeerName: t.PeerName})
		} else {
			edges = append(edges, ReplicationEdge{SideA: t.Source, SideB: t.Destination, PeerName: t.PeerName})
		}
	}
	return edges
}

// PolicyTemplateParams carries the parameters needed to create a
// NATIVE_REPLICATION ProtectionPolicy for one directed edge.
type PolicyTemplateParams struct {
	// OwnerName is the name of the VSCR/VVR object; used to derive the policy
	// name: "{ownerName}-{peerName}".
	OwnerName string
	// Frames is the replication schedule expressed as the VAST API "frames" array.
	// Each element is a map with keys: "every", "keep-local", "keep-remote",
	// and optionally "start-at".
	Frames []map[string]string
}

// SpecTemplateToParams converts a CRD ProtectionPolicyTemplate into the
// PolicyTemplateParams struct consumed by DiscoverLinkPolicies.
//
// ownerName is the name of the VSCR/VVR object and is used to derive the
// policy name: "{ownerName}-{peerName}".
func SpecTemplateToParams(ownerName string, tpl vastv1alpha1.ProtectionPolicyTemplate) PolicyTemplateParams {
	frames := make([]map[string]string, 0, len(tpl.Params))
	for _, f := range tpl.Params {
		m := map[string]string{"every": f.Every}
		if f.KeepLocal != "" {
			m["keep-local"] = f.KeepLocal
		}
		if f.KeepRemote != "" {
			m["keep-remote"] = f.KeepRemote
		}
		if f.StartAt != "" {
			m["start-at"] = f.StartAt
		}
		frames = append(frames, m)
	}
	return PolicyTemplateParams{
		OwnerName: ownerName,
		Frames:    frames,
	}
}

// buildNativeReplicaTargetsBySC lists replication peers (NativeReplicationRemoteTargets)
// for every StorageClass and returns a two-level map:
//
//	scName → peerName → *typed.ReplicationPeersDetailsModel
//
// The inner map is keyed by the peer's Name field (the shared peer name used on
// both sides of the link), and the PeerName field on each model is the remote
// cluster's own identifier for the local cluster.
func buildNativeReplicaTargetsBySC(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	wantPeerNames []string,
) (map[string]map[string]*typed.ReplicationPeersDetailsModel, error) {
	result := make(map[string]map[string]*typed.ReplicationPeersDetailsModel, len(restByStorageClass))
	for scName, rest := range restByStorageClass {
		peers, err := rest.ReplicationPeers.List(&typed.ReplicationPeersSearchParams{
			Name:    expr.Str.In(wantPeerNames...),
			RawData: vast_client.Params{"fields": "id,name,peer_name,status"},
		})
		if err != nil {
			return nil, fmt.Errorf("SC %s: failed to list replication peers: %w", scName, err)
		}
		byName := make(map[string]*typed.ReplicationPeersDetailsModel, len(peers))
		for _, p := range peers {
			byName[p.Name] = p
		}
		result[scName] = byName
	}
	return result, nil
}

// DiscoverLinkPolicies ensures the outbound NATIVE_REPLICATION ProtectionPolicy
// exists for every directed edge in the replication mesh.
//
// For each edge (SideA, SideB, PeerName) it:
//  1. Builds a mapping of NativeReplicationRemoteTargets per StorageClass.
//  2. If a policy named "{ownerName}-{peerName}" already exists it is returned
//     unchanged (policies are immutable after creation; no PATCH is ever issued).
//  3. Otherwise creates the policy with all fields including the schedule frames
//     and a snapshot prefix of "{sideA.PeerName}-{sideB.PeerName}".
//
// tenantByStorageClass must already contain an entry for every StorageClass in
// the mesh (typically status.tenantMapping).  Tenants are not re-resolved here.
//
// Returns a map from StorageClass name → outbound ReplicationLinks that
// should be attached as replication streams to that cluster's ppath.
func DiscoverLinkPolicies(
	restByStorageClass map[string]*vast_client.TypedVMSRest,
	tenantByStorageClass map[string]vastv1alpha1.TenantInfo,
	edges ReplicationEdgesList,
	tmpl PolicyTemplateParams,
	log *zap.Logger,
) (map[string][]ReplicationLink, error) {
	// Collect the peer names actually referenced in this topology so that the
	// API query (and its response log) contains only relevant peers.
	wantPeerNames := make([]string, 0, len(edges))
	for _, edge := range edges {
		wantPeerNames = append(wantPeerNames, edge.PeerName)
	}

	nativeTargets, err := buildNativeReplicaTargetsBySC(restByStorageClass, wantPeerNames)
	if err != nil {
		return nil, fmt.Errorf("failed to build native replication targets mapping: %w", err)
	}

	result := make(map[string][]ReplicationLink, len(restByStorageClass))

	for _, edge := range edges {
		restA, ok := restByStorageClass[edge.SideA]
		if !ok {
			return nil, fmt.Errorf("no REST client for StorageClass %q (SideA of link to %q via peer %q)",
				edge.SideA, edge.SideB, edge.PeerName)
		}
		restB, ok := restByStorageClass[edge.SideB]
		if !ok {
			return nil, fmt.Errorf("no REST client for StorageClass %q (SideB of link from %q via peer %q)",
				edge.SideB, edge.SideA, edge.PeerName)
		}
		localTenant, err := TenantFromMapping(tenantByStorageClass, edge.SideA)
		if err != nil {
			return nil, err
		}
		remoteTenant, err := TenantFromMapping(tenantByStorageClass, edge.SideB)
		if err != nil {
			return nil, err
		}

		peerA, ok := nativeTargets[edge.SideA][edge.PeerName]
		if !ok {
			return nil, fmt.Errorf("SC %s: replication peer %q not found in native replication targets",
				edge.SideA, edge.PeerName)
		}
		if peerA.Status != "OK" {
			return nil, fmt.Errorf("SC %s: replication peer %q is not healthy (status=%q); cannot create protection policy",
				edge.SideA, edge.PeerName, peerA.Status)
		}
		peerB, ok := nativeTargets[edge.SideB][edge.PeerName]
		if !ok {
			return nil, fmt.Errorf("SC %s: replication peer %q not found in native replication targets",
				edge.SideB, edge.PeerName)
		}
		if peerB.Status != "OK" {
			return nil, fmt.Errorf("SC %s: replication peer %q is not healthy (status=%q); cannot create protection policy",
				edge.SideB, edge.PeerName, peerB.Status)
		}
		prefix := tmpl.OwnerName + "-" + peerA.PeerName + "-" + peerB.PeerName

		pair, err := ensurePolicy(restA, edge, localTenant, remoteTenant, tmpl, peerA, peerB, prefix, log)
		if err != nil {
			return nil, err
		}

		// VAST automatically mirrors the ProtectionPolicy to SideB, but that
		// propagation is asynchronous.  Block until the mirror is visible so
		// that subsequent ppath creation on SideB can reference a valid policy.
		if err := WaitForResource(
			restB.Untyped.ProtectionPolicies,
			core.Params{"name": pair.PolicyName},
			WaitConditionPresent,
			policyMirrorTimeout,
			policyMirrorSleep,
			fmt.Sprintf("ProtectionPolicy %q to be mirrored on %q", pair.PolicyName, edge.SideB),
		); err != nil {
			return nil, fmt.Errorf(
				"SC %s: %w", edge.SideB, err)
		}

		result[edge.SideA] = append(result[edge.SideA], pair)
	}

	log.Info("all protection policies have been created successfully")
	return result, nil
}

// ensurePolicy idempotently ensures a NATIVE_REPLICATION ProtectionPolicy
// for the given directed edge.
//
// Policy name: "{ownerName}-{peerName}".
// The snapshot prefix is supplied by the caller and must be
// "{sideA.PeerName}-{sideB.PeerName}" — the concatenation of each side's
// remote peer identifier, joined by "-".
func ensurePolicy(
	rest *vast_client.TypedVMSRest,
	edge ReplicationEdge,
	localTenant, remoteTenant vastv1alpha1.TenantInfo,
	tmpl PolicyTemplateParams,
	peerA *typed.ReplicationPeersDetailsModel,
	peerB *typed.ReplicationPeersDetailsModel,
	prefix string,
	log *zap.Logger,
) (ReplicationLink, error) {
	policyName := tmpl.OwnerName + "-" + edge.PeerName

	// Fast path: return the existing policy without touching the peer API.
	if existing, err := rest.ProtectionPolicies.Get(&typed.ProtectionPolicySearchParams{Name: expr.S(policyName)}); err == nil {
		return newReplicationLink(existing.Name, existing.Id, peerA, peerB, edge, localTenant, remoteTenant), nil
	}

	log.Info("creating protection policy",
		zap.String("policy", policyName),
		zap.String("source_cluster", edge.SideA),
		zap.String("destination_cluster", edge.SideB),
		zap.Int64("tenant_id", localTenant.Id),
		zap.String("remote_tenant_guid", remoteTenant.Guid))

	rawFrames := make([]any, len(tmpl.Frames))
	for i, f := range tmpl.Frames {
		rawFrames[i] = f
	}
	record, err := rest.Untyped.ProtectionPolicies.Create(core.Params{
		"clone_type":         "NATIVE_REPLICATION",
		"name":               policyName,
		"target_object_id":   peerA.Id,
		"prefix":             prefix,
		"frames":             rawFrames,
		"tenant_id":          localTenant.Id,
		"remote_tenant_guid": remoteTenant.Guid,
	})
	if err != nil {
		return ReplicationLink{}, fmt.Errorf(
			"SC %s: failed to create ProtectionPolicy %q for peer %q: %w",
			edge.SideA, policyName, edge.PeerName, err)
	}

	var policy typed.ProtectionPolicyDetailsModel
	if err := record.Fill(&policy); err != nil {
		return ReplicationLink{}, fmt.Errorf(
			"SC %s: failed to decode ProtectionPolicy response for %q: %w",
			edge.SideA, policyName, err)
	}

	return newReplicationLink(policy.Name, policy.Id, peerA, peerB, edge, localTenant, remoteTenant), nil
}

// ProtectionPolicyNamesByStorageClass returns operator-created protection policy
// names grouped by StorageClass.  Each link's policy is created on SideA and
// mirrored to SideB, so both clusters may host snapshots under that policy name.
func ProtectionPolicyNamesByStorageClass(
	ownerName string,
	primarySC string,
	topology []vastv1alpha1.ReplicationTarget,
) map[string][]string {
	policyNamesBySC := make(map[string][]string)
	for _, t := range topology {
		if t.PeerName == "" {
			continue
		}
		policyName := ownerName + "-" + t.PeerName
		sideA := t.Source
		sideB := t.Destination
		if t.Destination == primarySC {
			sideA = t.Destination
			sideB = t.Source
		}
		policyNamesBySC[sideA] = append(policyNamesBySC[sideA], policyName)
		policyNamesBySC[sideB] = append(policyNamesBySC[sideB], policyName)
	}
	return policyNamesBySC
}

// DeleteProtectionPolicies deletes every NATIVE_REPLICATION ProtectionPolicy
// that was created for ownerName/topology.
func DeleteProtectionPolicies(
	ctx context.Context,
	k8s *k8s_client.K8sClient,
	ownerName string,
	primarySC string,
	topology []vastv1alpha1.ReplicationTarget,
	sslVerify bool,
	log *zap.Logger,
) {
	for scName, policyNames := range ProtectionPolicyNamesByStorageClass(ownerName, primarySC, topology) {
		rest, _, err := NewFromStorageClassName(ctx, k8s, scName, sslVerify, log)
		if err != nil {
			log.With(zap.Error(err)).Info("skipping protection policy deletion: cannot build REST client",
				zap.String("sc", scName))
			continue
		}
		for _, name := range policyNames {
			policy, err := rest.ProtectionPolicies.Get(&typed.ProtectionPolicySearchParams{Name: expr.S(name)})
			if err != nil {
				if vast_client.IsNotFoundErr(err) {
					continue
				}
				log.With(zap.Error(err)).Info("failed to look up protection policy for deletion",
					zap.String("policy", name))
				continue
			}
			if err := rest.ProtectionPolicies.DeleteById(policy.Id); err != nil {
				log.With(zap.Error(err)).Info("failed to delete protection policy",
					zap.String("policy", name))
			} else {
				log.Info("deleted protection policy", zap.String("policy", name))
			}
		}
	}
}

// newReplicationLink constructs a ReplicationLink from policy identity, peer
// models, and resolved tenants for both sides of the edge.
func newReplicationLink(
	policyName string,
	policyId int64,
	peerA *typed.ReplicationPeersDetailsModel,
	peerB *typed.ReplicationPeersDetailsModel,
	edge ReplicationEdge,
	localTenant, remoteTenant vastv1alpha1.TenantInfo,
) ReplicationLink {
	return ReplicationLink{
		PolicyName:           policyName,
		PolicyId:             policyId,
		LocalPeerTargetName:  peerA.Name,
		RemotePeerTargetName: peerB.Name,
		LocalPeerName:        peerA.PeerName,
		RemotePeerName:       peerB.PeerName,
		Edge: ReplicationLinkEdge{
			ReplicationEdge: edge,
			LocalTenant:     localTenant,
			RemoteTenant:    remoteTenant,
		},
	}
}
