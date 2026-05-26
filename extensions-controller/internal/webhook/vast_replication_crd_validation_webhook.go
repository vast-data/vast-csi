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

package webhook

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"go.uber.org/zap"
	admissionv1 "k8s.io/api/admission/v1"
	"sigs.k8s.io/controller-runtime/pkg/manager"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"

	vast_client "github.com/vast-data/go-vast-client"
	"github.com/vast-data/go-vast-client/resources/typed"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/ppathdir"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/vmsrest"
)

// Webhook paths for the admission webhooks.
const (
	VSCRValidatePath = "/validate-vastdata-com-v1alpha1-vaststorageclassreplication"
	VVRValidatePath  = "/validate-vastdata-com-v1alpha1-vastvolumereplication"
)

// replicationCRDValidator validates (and defaults) VastStorageClassReplication
// and VastVolumeReplication objects on admission.
//
// On CREATE it performs full validation including live VAST REST calls:
//  1. Each topology entry's StorageClasses must exist in Kubernetes.
//  2. The two VAST clusters must share exactly the named ReplicationPeer; if
//     peerName is omitted, the single shared peer is discovered automatically
//     and written back to the object (defaulting mutation).
//  3. Each StorageClass may appear in at most one VSCR; VVRs may reuse SCs.
type replicationCRDValidator struct {
	k8sClient *k8sclient.K8sClient
	sslVerify bool
	rainbow   *logging.RainbowLogger
	decoder   admission.Decoder
}

// vscrAdmissionHandler wraps replicationCRDValidator for VSCR objects.
type vscrAdmissionHandler struct{ *replicationCRDValidator }

// vvrAdmissionHandler wraps replicationCRDValidator for VVR objects.
type vvrAdmissionHandler struct{ *replicationCRDValidator }

// Handle implements admission.Handler for VastStorageClassReplication.
func (h *vscrAdmissionHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	log := h.rainbow.For("vscr", req.Namespace+"/"+req.Name)

	obj := &vastv1alpha1.VastStorageClassReplication{}
	if err := h.decoder.Decode(req, obj); err != nil {
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Update {
		old := &vastv1alpha1.VastStorageClassReplication{}
		if err := h.decoder.DecodeRaw(req.OldObject, old); err != nil {
			return admission.Errored(http.StatusBadRequest, err)
		}
		if resp := validateTopologyImmutable(old.Spec.ProtectionTopology, obj.Spec.ProtectionTopology); !resp.Allowed {
			return resp
		}
	}

	if err := obj.Spec.Validate(); err != nil {
		return admission.Denied(err.Error())
	}

	if req.Operation == admissionv1.Create {
		if resp := h.validateAndDefaultTopology(ctx, log, req, obj.Spec.ProtectionTopology); !resp.Allowed {
			return resp
		}

		primarySC, err := h.k8sClient.GetStorageClass(ctx, obj.Spec.PrimaryStorageClass)
		if err != nil {
			return admission.Denied(fmt.Sprintf("primaryStorageClass %q not found: %v", obj.Spec.PrimaryStorageClass, err))
		}
		if k8sclient.IsBlockStorageClass(primarySC) {
			if ppathdir.IsSubsystemLevel(h.k8sClient, primarySC) {
				if resp := h.validateSubsystemLevelTenantName(ctx, obj.Spec.PrimaryStorageClass, obj.Spec.AllStorageClasses()); !resp.Allowed {
					return resp
				}
				var secondarySCNames []string
				for _, scName := range obj.Spec.AllStorageClasses() {
					if scName != obj.Spec.PrimaryStorageClass {
						secondarySCNames = append(secondarySCNames, scName)
					}
				}
				if resp := h.validateSubsystemPresence(ctx, log, secondarySCNames, false); !resp.Allowed {
					return resp
				}
			} else {
				if resp := h.validateSubsystemPresence(ctx, log, obj.Spec.AllStorageClasses(), true); !resp.Allowed {
					return resp
				}
			}
		}
	}

	if resp := h.validateStorageClassConsistency(ctx, obj.Spec.AllStorageClasses()); !resp.Allowed {
		return resp
	}

	return h.validate(ctx, log, obj.Namespace, obj.Name, "VastStorageClassReplication",
		obj.Spec.AllStorageClasses())
}

// Handle implements admission.Handler for VastVolumeReplication.
func (h *vvrAdmissionHandler) Handle(ctx context.Context, req admission.Request) admission.Response {
	log := h.rainbow.For("vvr", req.Namespace+"/"+req.Name)

	obj := &vastv1alpha1.VastVolumeReplication{}
	if err := h.decoder.Decode(req, obj); err != nil {
		return admission.Errored(http.StatusBadRequest, err)
	}

	if req.Operation == admissionv1.Update {
		old := &vastv1alpha1.VastVolumeReplication{}
		if err := h.decoder.DecodeRaw(req.OldObject, old); err != nil {
			return admission.Errored(http.StatusBadRequest, err)
		}
		if resp := validateTopologyImmutable(old.Spec.ProtectionTopology, obj.Spec.ProtectionTopology); !resp.Allowed {
			return resp
		}
	}

	if err := obj.Spec.Validate(); err != nil {
		return admission.Denied(err.Error())
	}

	if req.Operation == admissionv1.Create {
		if resp := h.validateAndDefaultTopology(ctx, log, req, obj.Spec.ProtectionTopology); !resp.Allowed {
			return resp
		}
		if resp := h.validateVVRPVCStorageClass(ctx, obj); !resp.Allowed {
			return resp
		}
		// VVR is never subsystem-level: the subsystem must already exist on all clusters.
		if resp := h.validateSubsystemPresence(ctx, log, obj.Spec.AllStorageClasses(), true); !resp.Allowed {
			return resp
		}
	}

	if resp := h.validateStorageClassConsistency(ctx, obj.Spec.AllStorageClasses()); !resp.Allowed {
		return resp
	}

	log.Info("replication CRD validation passed",
		zap.String("kind", "VastVolumeReplication"),
		zap.String("name", obj.Name),
		zap.Strings("storageClasses", obj.Spec.AllStorageClasses()))
	return admission.Allowed("")
}

// validateVVRPVCStorageClass checks that the PVC referenced by spec.volumeName
// was provisioned by spec.primaryStorageClass.  This is enforced on CREATE only.
func (h *replicationCRDValidator) validateVVRPVCStorageClass(
	ctx context.Context,
	obj *vastv1alpha1.VastVolumeReplication,
) admission.Response {
	pvc, err := h.k8sClient.GetPVC(ctx, obj.Spec.VolumeName, obj.Namespace)
	if err != nil {
		return admission.Denied(fmt.Sprintf(
			"spec.volumeName: PVC %s/%s not found: %v",
			obj.Namespace, obj.Spec.VolumeName, err,
		))
	}
	if pvc.Spec.StorageClassName == nil || *pvc.Spec.StorageClassName == "" {
		return admission.Denied(fmt.Sprintf(
			"spec.volumeName: PVC %s/%s has no StorageClass set",
			obj.Namespace, obj.Spec.VolumeName,
		))
	}
	if *pvc.Spec.StorageClassName != obj.Spec.PrimaryStorageClass {
		return admission.Denied(fmt.Sprintf(
			"spec.primaryStorageClass %q does not match the StorageClass of PVC %s/%s (%q); "+
				"the PVC must be provisioned by the primary StorageClass",
			obj.Spec.PrimaryStorageClass, obj.Namespace, obj.Spec.VolumeName,
			*pvc.Spec.StorageClassName,
		))
	}
	return admission.Allowed("")
}

// validateAndDefaultTopology validates each topology entry via live REST calls
// and auto-discovers any empty peerName fields.  If any peerNames were
// discovered the modified object is returned as a JSON-patch response so the
// defaulted values are persisted to the API server.
func (h *replicationCRDValidator) validateAndDefaultTopology(
	ctx context.Context,
	log *zap.Logger,
	req admission.Request,
	topology []vastv1alpha1.ReplicationTarget,
) admission.Response {
	// Build one REST client per unique StorageClass, then fetch the peer list
	// from each cluster exactly once.  Without this, clusters that appear in
	// multiple topology entries (e.g. the primary in A→B and A→C) would be
	// queried once per edge.
	restByStorageClass := make(map[string]*vast_client.TypedVMSRest)
	for i := range topology {
		t := &topology[i]
		for _, scName := range []string{t.Source, t.Destination} {
			if _, ok := restByStorageClass[scName]; ok {
				continue
			}
			sc, err := h.k8sClient.GetStorageClass(ctx, scName)
			if err != nil {
				return admission.Denied(fmt.Sprintf("protectionTopology[%d]: StorageClass %q not found: %v", i, scName, err))
			}
			rest, err := vmsrest.NewFromStorageClass(ctx, h.k8sClient, sc, h.sslVerify, log)
			if err != nil {
				return admission.Errored(http.StatusInternalServerError,
					fmt.Errorf("protectionTopology[%d]: REST client for %q: %w", i, scName, err))
			}
			restByStorageClass[scName] = rest
		}
	}
	peersBySC, err := vmsrest.BuildPeerNamesBySC(restByStorageClass)
	if err != nil {
		return admission.Errored(http.StatusInternalServerError,
			fmt.Errorf("failed to list replication peers: %w", err))
	}

	for i := range topology {
		t := &topology[i]
		if err := vmsrest.ResolvePeerName(t, peersBySC); err != nil {
			return admission.Denied(fmt.Sprintf("protectionTopology[%d]: %v", i, err))
		}
	}

	// If any peerNames were auto-discovered we need to patch the object so the
	// defaulted values are persisted.  We re-marshal from req.Object.Raw and
	// produce a merge-patch containing only the changed peerName fields.
	modified, err := applyTopologyDefaults(req.Object.Raw, topology)
	if err != nil {
		return admission.Errored(http.StatusInternalServerError, err)
	}
	if modified != nil {
		return admission.PatchResponseFromRaw(req.Object.Raw, modified)
	}
	return admission.Allowed("")
}

// applyTopologyDefaults re-encodes the original raw object with any peerNames
// that were defaulted during validation.  Returns nil if nothing changed.
func applyTopologyDefaults(originalRaw []byte, topology []vastv1alpha1.ReplicationTarget) ([]byte, error) {
	// Decode into a generic map so we can surgically update peerName fields.
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(originalRaw, &raw); err != nil {
		return nil, fmt.Errorf("unmarshal object: %w", err)
	}
	specRaw, ok := raw["spec"]
	if !ok {
		return nil, nil
	}
	var spec map[string]json.RawMessage
	if err := json.Unmarshal(specRaw, &spec); err != nil {
		return nil, fmt.Errorf("unmarshal spec: %w", err)
	}
	topologyRaw, ok := spec["protectionTopology"]
	if !ok {
		return nil, nil
	}
	var entries []map[string]json.RawMessage
	if err := json.Unmarshal(topologyRaw, &entries); err != nil {
		return nil, fmt.Errorf("unmarshal protectionTopology: %w", err)
	}

	changed := false
	for i, t := range topology {
		if i >= len(entries) {
			break
		}
		// Check if peerName was absent or empty in the original.
		origPeer, _ := entries[i]["peerName"]
		if len(origPeer) == 0 || string(origPeer) == `""` || string(origPeer) == "null" {
			if t.PeerName != "" {
				encoded, err := json.Marshal(t.PeerName)
				if err != nil {
					return nil, err
				}
				entries[i]["peerName"] = encoded
				changed = true
			}
		}
	}

	if !changed {
		return nil, nil
	}

	// Re-encode the mutated object.
	newTopology, err := json.Marshal(entries)
	if err != nil {
		return nil, fmt.Errorf("marshal updated protectionTopology: %w", err)
	}
	spec["protectionTopology"] = newTopology
	newSpec, err := json.Marshal(spec)
	if err != nil {
		return nil, fmt.Errorf("marshal updated spec: %w", err)
	}
	raw["spec"] = newSpec
	return json.Marshal(raw)
}

// validateTopologyImmutable denies any UPDATE that changes the structural shape
// of the replication topology.  Source and Destination are immutable once set;
// PeerName is allowed to change (the controller and webhook may fill it in after
// initial creation via auto-discovery).
func validateTopologyImmutable(oldTopology, newTopology []vastv1alpha1.ReplicationTarget) admission.Response {
	if len(oldTopology) != len(newTopology) {
		return admission.Denied(
			"protectionTopology is immutable: the number of entries cannot change after creation")
	}
	for i := range oldTopology {
		o, n := oldTopology[i], newTopology[i]
		if o.Source != n.Source || o.Destination != n.Destination {
			return admission.Denied(fmt.Sprintf(
				"protectionTopology[%d] is immutable: source/destination cannot change after creation "+
					"(was %q→%q, got %q→%q)",
				i, o.Source, o.Destination, n.Source, n.Destination))
		}
	}
	return admission.Allowed("")
}

// validate checks that none of storageClasses are already claimed by another
// VSCR or VVR in the cluster (VSCR admission only), excluding self on UPDATE.
func (v *replicationCRDValidator) validate(
	ctx context.Context,
	log *zap.Logger,
	namespace, name, kind string,
	storageClasses []string,
) admission.Response {
	incoming := make(map[string]struct{}, len(storageClasses))
	for _, sc := range storageClasses {
		incoming[sc] = struct{}{}
	}

	// used maps SC name → "Kind namespace/name" of the owning object.
	used := make(map[string]string)

	vscrList, err := v.k8sClient.ListVastStorageClassReplications(ctx, "")
	if err != nil {
		return admission.Errored(http.StatusInternalServerError, err)
	}
	for _, vscr := range vscrList {
		if kind == "VastStorageClassReplication" && vscr.Name == name && vscr.Namespace == namespace {
			continue // skip self (UPDATE path)
		}
		for _, sc := range vscr.Spec.AllStorageClasses() {
			used[sc] = fmt.Sprintf("VastStorageClassReplication %s/%s", vscr.Namespace, vscr.Name)
		}
	}

	vvrList, err := v.k8sClient.ListVastVolumeReplications(ctx, "")
	if err != nil {
		return admission.Errored(http.StatusInternalServerError, err)
	}
	for _, vvr := range vvrList {
		if kind == "VastVolumeReplication" && vvr.Name == name && vvr.Namespace == namespace {
			continue // skip self (UPDATE path)
		}
		for _, sc := range vvr.Spec.AllStorageClasses() {
			used[sc] = fmt.Sprintf("VastVolumeReplication %s/%s", vvr.Namespace, vvr.Name)
		}
	}

	for sc := range incoming {
		if owner, ok := used[sc]; ok {
			return admission.Denied(
				fmt.Sprintf("StorageClass %q is already used by %s; each StorageClass may appear in at most one VastStorageClassReplication or VastVolumeReplication",
					sc, owner))
		}
	}

	log.Info("replication CRD validation passed",
		zap.String("kind", kind),
		zap.String("name", name),
		zap.Strings("storageClasses", storageClasses))

	return admission.Allowed("")
}

// validateStorageClassConsistency ensures that all StorageClasses in the list
// use the same CSI driver type (all block or all file).  Mixing block and file
// StorageClasses within a single replication object is rejected because they
// require fundamentally different replication mechanics.
//
// Path-level parameters (subsystem, volume_group, root_export) may differ
// across clusters — each cluster's ppath directory is predicted independently.
func (v *replicationCRDValidator) validateStorageClassConsistency(
	ctx context.Context,
	storageClasses []string,
) admission.Response {
	if len(storageClasses) < 2 {
		return admission.Allowed("")
	}

	driverType := func(isBlock bool) string {
		if isBlock {
			return "block"
		}
		return "file"
	}

	firstSC, err := v.k8sClient.GetStorageClass(ctx, storageClasses[0])
	if err != nil {
		return admission.Denied(fmt.Sprintf("StorageClass %q not found: %v", storageClasses[0], err))
	}
	firstIsBlock := k8sclient.IsBlockStorageClass(firstSC)

	for _, scName := range storageClasses[1:] {
		sc, err := v.k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return admission.Denied(fmt.Sprintf("StorageClass %q not found: %v", scName, err))
		}
		if k8sclient.IsBlockStorageClass(sc) != firstIsBlock {
			return admission.Denied(fmt.Sprintf(
				"StorageClass %q is a %s driver but %q is a %s driver; all StorageClasses must use the same driver type",
				scName, driverType(k8sclient.IsBlockStorageClass(sc)),
				storageClasses[0], driverType(firstIsBlock)))
		}
	}

	return admission.Allowed("")
}

// validateSubsystemLevelTenantName checks that every secondary StorageClass in a
// subsystem-level VSCR carries a "tenant_name" parameter.
//
// The subsystem does not yet exist on secondary clusters (VAST creates it via
// the replication stream), so tenant resolution cannot fall back to a view
// lookup — "tenant_name" must be provided explicitly.
func (v *replicationCRDValidator) validateSubsystemLevelTenantName(
	ctx context.Context,
	primarySCName string,
	allSCNames []string,
) admission.Response {
	for _, scName := range allSCNames {
		if scName == primarySCName {
			continue
		}
		sc, err := v.k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return admission.Denied(fmt.Sprintf("StorageClass %q not found: %v", scName, err))
		}
		if sc.Parameters["tenant_name"] == "" {
			return admission.Denied(fmt.Sprintf(
				"StorageClass %q is missing required parameter \"tenant_name\": "+
					"subsystem-level block replication cannot resolve the tenant on secondary clusters "+
					"before the subsystem exists — set \"tenant_name\" to the target tenant's name",
				scName,
			))
		}
	}
	return admission.Allowed("")
}

// validateSubsystemPresence checks whether the block subsystem (view) is present
// or absent on each cluster in scNames.
//
//   - mustExist=true:  subsystem must be found    (VVR and non-subsystem-level VSCR).
//   - mustExist=false: subsystem must be absent   (subsystem-level VSCR secondaries).
func (v *replicationCRDValidator) validateSubsystemPresence(
	ctx context.Context,
	log *zap.Logger,
	scNames []string,
	mustExist bool,
) admission.Response {
	for _, scName := range scNames {
		sc, err := v.k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return admission.Denied(fmt.Sprintf("StorageClass %q not found: %v", scName, err))
		}
		if !k8sclient.IsBlockStorageClass(sc) {
			continue
		}
		subsystemName := sc.Parameters[common.StorageClassParameterSubsystem]
		if subsystemName == "" {
			return admission.Denied(fmt.Sprintf(
				"StorageClass %q is missing required parameter %q",
				scName, common.StorageClassParameterSubsystem,
			))
		}
		rest, err := vmsrest.NewFromStorageClass(ctx, v.k8sClient, sc, v.sslVerify, log)
		if err != nil {
			return admission.Errored(http.StatusInternalServerError,
				fmt.Errorf("StorageClass %q: failed to build REST client: %w", scName, err))
		}
		params := vast_client.Params{"name": subsystemName}
		if tn := sc.Parameters["tenant_name"]; tn != "" {
			params["tenant_name"] = tn
		}
		exists, err := rest.Views.ExistsWithContext(ctx, &typed.ViewSearchParams{RawData: params})
		if err != nil {
			return admission.Errored(http.StatusInternalServerError,
				fmt.Errorf("StorageClass %q: failed to check subsystem %q on cluster: %w", scName, subsystemName, err))
		}
		if mustExist && !exists {
			return admission.Denied(fmt.Sprintf(
				"StorageClass %q: subsystem %q does not exist on cluster; "+
					"for block replication the subsystem must be pre-created on all clusters",
				scName, subsystemName,
			))
		}
		if !mustExist && exists {
			return admission.Denied(fmt.Sprintf(
				"subsystem-level block replication requires that subsystem %q does not pre-exist "+
					"on secondary cluster (StorageClass %q): VAST creates it via replication; "+
					"delete the subsystem from the secondary cluster and retry",
				subsystemName, scName,
			))
		}
	}
	return admission.Allowed("")
}

// SetupReplicationCRDValidationWebhooks registers the admission webhooks for
// VastStorageClassReplication and VastVolumeReplication with mgr.
func SetupReplicationCRDValidationWebhooks(
	mgr manager.Manager,
	k8sClient *k8sclient.K8sClient,
	sslVerify bool,
	rainbow *logging.RainbowLogger,
) {
	decoder := admission.NewDecoder(mgr.GetScheme())
	base := &replicationCRDValidator{
		k8sClient: k8sClient,
		sslVerify: sslVerify,
		rainbow:   rainbow,
		decoder:   decoder,
	}

	mgr.GetWebhookServer().Register(VSCRValidatePath,
		&admission.Webhook{Handler: &vscrAdmissionHandler{base}})
	mgr.GetWebhookServer().Register(VVRValidatePath,
		&admission.Webhook{Handler: &vvrAdmissionHandler{base}})

	rainbow.For("webhook", "setup").Info("registered replication CRD admission webhooks",
		zap.String("vscr_path", VSCRValidatePath),
		zap.String("vvr_path", VVRValidatePath))
}
