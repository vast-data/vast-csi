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
	"regexp"
	"strings"
	"sync"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/errors"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
)

const webhookPath = "/mutate-pvc"

// scInfo holds the fields from a StorageClass that the webhook cares about.
// Provisioner and StorageClass parameters are effectively immutable once a
// StorageClass is created, so caching this struct for the process lifetime
// is safe.
type scInfo struct {
	provisioner string
	subsystem   string
}

// PVCLabelInjector handles mutating admission requests for PVCs.
// It reads StorageClass parameters and injects replication labels.
type PVCLabelInjector struct {
	K8sClient *k8s_client.K8sClient
	Decoder   admission.Decoder
	Config    *config.Config
	Rainbow   *logging.RainbowLogger

	// Cached compiled regexes
	storageClassNameRegex *regexp.Regexp
	pvcNameRegex          *regexp.Regexp
	regexOnce             sync.Once

	// scCache maps storageClassName → scInfo.
	scCache   map[string]scInfo
	scCacheMu sync.RWMutex
}

// cachedSCInfo returns the scInfo for scName, fetching and caching the
// StorageClass from the API server on first access.
func (p *PVCLabelInjector) cachedSCInfo(ctx context.Context, scName string) (scInfo, error) {
	p.scCacheMu.RLock()
	info, ok := p.scCache[scName]
	p.scCacheMu.RUnlock()
	if ok {
		return info, nil
	}

	sc, err := p.K8sClient.GetStorageClass(ctx, scName)
	if err != nil {
		return scInfo{}, err
	}
	info = scInfo{
		provisioner: sc.Provisioner,
		subsystem:   sc.Parameters[common.StorageClassParameterSubsystem],
	}

	p.scCacheMu.Lock()
	p.scCache[scName] = info
	p.scCacheMu.Unlock()

	return info, nil
}

func (p *PVCLabelInjector) Handle(ctx context.Context, req admission.Request) admission.Response {
	log := p.Rainbow.For("pvc", req.Namespace+"/"+req.Name)

	pvc := new(corev1.PersistentVolumeClaim)
	if err := p.Decoder.Decode(req, pvc); err != nil {
		log.Error("failed to decode PVC", zap.Error(err))
		return admission.Allowed("decode error, skipping")
	}

	scName := ""
	if pvc.Spec.StorageClassName != nil {
		scName = *pvc.Spec.StorageClassName
	}
	if scName == "" {
		return admission.Allowed("no storageClassName")
	}

	// Fetch SC info (cached after first access per StorageClass name).
	// Done before the SC-name / PVC-name filters so that both the
	// replication-state check AND the label injection use the same result.
	info, err := p.cachedSCInfo(ctx, scName)
	if err != nil {
		if errors.IsNotFound(err) {
			log.Info("StorageClass not found, skipping",
				zap.String("storageClass", scName))
			return admission.Allowed("storageClass not found")
		}
		// Network / permissions errors: fail open.
		log.Error("failed to get StorageClass, skipping",
			zap.String("storageClass", scName),
			zap.Error(err))
		return admission.Allowed("failed to get storageClass")
	}

	// CSI driver name filter: skip if the SC's provisioner doesn't match.
	if p.Config.CSIDriverName != "" && info.provisioner != p.Config.CSIDriverName {
		log.Info("StorageClass provisioner does not match CSI driver filter, skipping",
			zap.String("provisioner", info.provisioner),
			zap.String("csiDriverName", p.Config.CSIDriverName))
		return admission.Allowed("provisioner does not match csi-driver-name filter")
	}

	// Mirror PVCs are created by the extensions controller itself on secondary
	// clusters as part of constellation sync.
	if pvc.Labels[common.LabelManagedBy] == common.LabelManagedByValue {
		log.Debug("managed mirror PVC — skipping replication state validation")
	} else {
		// Deny PVC creation when the cluster for this StorageClass is currently
		// acting as a replication secondary (read-only destination).
		if denied, msg := p.checkReplicationState(ctx, pvc.Namespace, scName, log); denied {
			return admission.Denied(msg)
		}
	}

	// Label injection: only applies when the SC-name and PVC-name filters match.
	if !p.matchesStorageClassFilter(scName) {
		log.Info("StorageClass does not match filter, skipping label injection",
			zap.String("storageClass", scName))
		return admission.Allowed("storageClass does not match filter")
	}
	if !p.matchesPVCNameFilter(pvc.Name) {
		log.Info("PVC name does not match filter, skipping label injection")
		return admission.Allowed("PVC name does not match filter")
	}

	modified := false

	if !p.K8sClient.HasLabel(pvc, common.LabelStorageClass) {
		p.K8sClient.SetLabel(pvc, common.LabelStorageClass, scName)
		modified = true
	}

	if info.subsystem != "" && !p.K8sClient.HasLabel(pvc, common.LabelSubsystem) {
		p.K8sClient.SetLabel(pvc, common.LabelSubsystem, info.subsystem)
		modified = true
	}

	if !modified {
		return admission.Allowed("labels already present")
	}

	log.Info("injecting replication labels",
		zap.String("storageClass", scName),
		zap.String("subsystem", info.subsystem),
	)

	marshaledPVC, err := json.Marshal(pvc)
	if err != nil {
		log.Error("failed to marshal PVC", zap.Error(err))
		return admission.Allowed("marshal error, skipping")
	}

	return admission.PatchResponseFromRaw(req.Object.Raw, marshaledPVC)
}

// checkReplicationState queries VolumeGroupReplications and VolumeReplications
// managed by this controller for the given StorageClass.  If any reports a
// current status.state of Secondary the PVC is from a read-only replication
// site and must be rejected.
func (p *PVCLabelInjector) checkReplicationState(
	ctx context.Context,
	namespace, scName string,
	log *zap.Logger,
) (denied bool, message string) {
	sel := map[string]string{
		common.LabelManagedBy:    common.LabelManagedByValue,
		common.LabelStorageClass: scName,
	}

	// Check VolumeGroupReplications (created by VastStorageClassReplication).
	vgrs, err := p.K8sClient.ListVolumeGroupReplicationsByLabelSelector(ctx, namespace, sel)
	if err != nil {
		log.Warn("failed to list VolumeGroupReplications for replication state check",
			zap.String("storageClass", scName), zap.Error(err))
	} else {
		for _, vgr := range vgrs {
			if vgr.Status.State == replicationv1alpha1.SecondaryState &&
				vgr.Spec.ReplicationState != replicationv1alpha1.Resync {
				// csi-addons also reports status.State=Secondary while
				// spec.ReplicationState=Resync (a labelling quirk in
				// GetReplicationState).  That is a transient resync — the storage
				// is still the SOURCE, so PVC creation must be allowed.
				log.Info("denying PVC: StorageClass is on a secondary replication site",
					zap.String("storageClass", scName),
					zap.String("vgr", vgr.Name),
					zap.String("state", string(vgr.Status.State)))
				return true, fmt.Sprintf(
					"StorageClass %q is currently a replication secondary (read-only). "+
						"PVC creation is not allowed on a read-only cluster. "+
						"Promote this cluster to primary first.",
					scName)
			}
		}
	}

	// Check VolumeReplications (created by VastVolumeReplication).
	vrs, err := p.K8sClient.ListVolumeReplicationsByLabelSelector(ctx, namespace, sel)
	if err != nil {
		log.Warn("failed to list VolumeReplications for replication state check",
			zap.String("storageClass", scName), zap.Error(err))
	} else {
		for _, vr := range vrs {
			if vr.Status.State == replicationv1alpha1.SecondaryState &&
				vr.Spec.ReplicationState != replicationv1alpha1.Resync {
				log.Info("denying PVC: StorageClass is on a secondary replication site",
					zap.String("storageClass", scName),
					zap.String("vr", vr.Name),
					zap.String("state", string(vr.Status.State)))
				return true, fmt.Sprintf(
					"StorageClass %q is currently a replication secondary (read-only). "+
						"PVC creation is not allowed on a read-only cluster. "+
						"Promote this cluster to primary first.",
					scName)
			}
		}
	}

	return false, ""
}

// compileRegexes compiles regex patterns from config strings once.
func (p *PVCLabelInjector) compileRegexes() {
	p.regexOnce.Do(func() {
		if p.Config.StorageClassNameRegex != "" {
			p.storageClassNameRegex = regexp.MustCompile(p.Config.StorageClassNameRegex)
		}
		if p.Config.PVCNameRegex != "" {
			p.pvcNameRegex = regexp.MustCompile(p.Config.PVCNameRegex)
		}
	})
}

func (p *PVCLabelInjector) matchesStorageClassFilter(scName string) bool {
	p.compileRegexes()

	if p.Config.StorageClassName != "" {
		return scName == p.Config.StorageClassName
	}
	if p.storageClassNameRegex != nil {
		return p.storageClassNameRegex.MatchString(scName)
	}
	return true
}

func (p *PVCLabelInjector) matchesPVCNameFilter(pvcName string) bool {
	p.compileRegexes()

	if p.pvcNameRegex != nil {
		return p.pvcNameRegex.MatchString(pvcName)
	}
	return true
}

// sanitizeLabelValue converts a string to a valid Kubernetes label value.
// Label values must be <= 63 chars, start/end with alphanumeric, and contain
// only [-_.a-zA-Z0-9].
func sanitizeLabelValue(value string) string {
	if value == "" {
		return ""
	}
	sanitized := common.InvalidLabelCharsRegex.ReplaceAllString(value, "_")
	sanitized = strings.Trim(sanitized, "-_.")
	if len(sanitized) > 63 {
		sanitized = sanitized[:63]
	}
	return sanitized
}

// SetupWithManager registers the PVC label injector webhook with the manager.
func SetupWithManager(mgr ctrl.Manager, k8sClient *k8s_client.K8sClient, cfg *config.Config, rainbow *logging.RainbowLogger) error {
	decoder := admission.NewDecoder(mgr.GetScheme())
	mgr.GetWebhookServer().Register(webhookPath, &admission.Webhook{
		Handler: &PVCLabelInjector{
			K8sClient: k8sClient,
			Decoder:   decoder,
			Config:    cfg,
			Rainbow:   rainbow,
			scCache:   make(map[string]scInfo),
		},
	})
	return nil
}
