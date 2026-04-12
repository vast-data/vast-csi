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

	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
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
//  3. Each StorageClass may appear in at most one VSCR or VVR.
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
	}

	if resp := h.validateStorageClassConsistency(ctx, obj.Spec.AllStorageClasses()); !resp.Allowed {
		return resp
	}

	return h.validate(ctx, log, obj.Namespace, obj.Name, "VastVolumeReplication",
		obj.Spec.AllStorageClasses())
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
	for i := range topology {
		t := &topology[i]

		scSrc, err := h.k8sClient.GetStorageClass(ctx, t.Source)
		if err != nil {
			return admission.Denied(fmt.Sprintf("protectionTopology[%d]: source StorageClass %q not found: %v", i, t.Source, err))
		}
		scDst, err := h.k8sClient.GetStorageClass(ctx, t.Destination)
		if err != nil {
			return admission.Denied(fmt.Sprintf("protectionTopology[%d]: destination StorageClass %q not found: %v", i, t.Destination, err))
		}

		restSrc, err := vmsrest.NewFromStorageClass(ctx, h.k8sClient, scSrc, h.sslVerify, log)
		if err != nil {
			return admission.Errored(http.StatusInternalServerError,
				fmt.Errorf("protectionTopology[%d]: REST client for source %q: %w", i, t.Source, err))
		}
		restDst, err := vmsrest.NewFromStorageClass(ctx, h.k8sClient, scDst, h.sslVerify, log)
		if err != nil {
			return admission.Errored(http.StatusInternalServerError,
				fmt.Errorf("protectionTopology[%d]: REST client for destination %q: %w", i, t.Destination, err))
		}

		if err := vmsrest.ResolvePeerName(t, restSrc, restDst); err != nil {
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
// VSCR or VVR in the cluster, excluding the object being updated (self on UPDATE).
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
// agree on the CSI driver type and on the key parameters that determine the
// target storage path:
//
//   - Block driver (StorageClass has a "subsystem" parameter): every class must
//     share the same "subsystem" and "volume_group" values.
//   - File driver (StorageClass has a "root_export" parameter): every class must
//     share the same "root_export" value.
//
// Mixing block and file StorageClasses within a single replication object is
// also rejected.
func (v *replicationCRDValidator) validateStorageClassConsistency(
	ctx context.Context,
	storageClasses []string,
) admission.Response {
	if len(storageClasses) < 2 {
		return admission.Allowed("")
	}

	type scParams struct {
		isBlock     bool
		subsystem   string
		volumeGroup string
		rootExport  string
	}

	params := make([]scParams, 0, len(storageClasses))
	for _, scName := range storageClasses {
		sc, err := v.k8sClient.GetStorageClass(ctx, scName)
		if err != nil {
			return admission.Denied(fmt.Sprintf("StorageClass %q not found: %v", scName, err))
		}

		p := scParams{}

		p.isBlock = k8sclient.IsBlockStorageClass(sc)
		subsystem, _ := sc.Parameters[common.StorageClassParameterSubsystem]
		rootExport, _ := sc.Parameters[common.StorageClassParameterRootExport]
		p.subsystem = subsystem
		p.volumeGroup = sc.Parameters[common.StorageClassParameterVolumeGroup]
		p.rootExport = rootExport
		params = append(params, p)
	}

	// All StorageClasses must be the same driver type.
	first := params[0]
	for i, p := range params[1:] {
		scName := storageClasses[i+1]
		if p.isBlock != first.isBlock {
			driverType := func(isBlock bool) string {
				if isBlock {
					return "block"
				}
				return "file"
			}
			return admission.Denied(fmt.Sprintf(
				"StorageClass %q is a %s driver but %q is a %s driver; all StorageClasses must use the same driver type",
				scName, driverType(p.isBlock), storageClasses[0], driverType(first.isBlock)))
		}
	}

	// Validate that the routing parameters are identical across all classes.
	if first.isBlock {
		for i, p := range params[1:] {
			scName := storageClasses[i+1]
			if p.subsystem != first.subsystem {
				return admission.Denied(fmt.Sprintf(
					"StorageClass %q has %s=%q but %q has %s=%q; all StorageClasses must share the same subsystem",
					scName, common.StorageClassParameterSubsystem, p.subsystem,
					storageClasses[0], common.StorageClassParameterSubsystem, first.subsystem))
			}
			if p.volumeGroup != first.volumeGroup {
				return admission.Denied(fmt.Sprintf(
					"StorageClass %q has %s=%q but %q has %s=%q; all StorageClasses must share the same volume_group",
					scName, common.StorageClassParameterVolumeGroup, p.volumeGroup,
					storageClasses[0], common.StorageClassParameterVolumeGroup, first.volumeGroup))
			}
		}
	} else {
		for i, p := range params[1:] {
			scName := storageClasses[i+1]
			if p.rootExport != first.rootExport {
				return admission.Denied(fmt.Sprintf(
					"StorageClass %q has %s=%q but %q has %s=%q; all StorageClasses must share the same root_export",
					scName, common.StorageClassParameterRootExport, p.rootExport,
					storageClasses[0], common.StorageClassParameterRootExport, first.rootExport))
			}
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
