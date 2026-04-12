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

package controller

// PVC remap on failover
//
// PVCRemapReconciler is a single controller that handles PVC remapping for
// both VastStorageClassReplication (VSCR) and VastVolumeReplication (VVR).
//
// Remap model — siblings
//
// Every managed mirror PVC carries a LabelSourcePVC label pointing at the
// original source PVC (which itself carries no special label).  For a group
// with source pvc1, mirror pvc2 (clusterB), and mirror pvc3 (clusterC):
//
//   pvc2.labels[LabelSourcePVC] = "pvc1"
//   pvc3.labels[LabelSourcePVC] = "pvc1"
//
// When pvc2 becomes primary the remap table is:
//   pvc1 → pvc2   (original source → new primary mirror)
//   pvc3 → pvc2   (other mirror    → new primary mirror)
//
// When pvc1 becomes primary again (failback) the remap table is:
//   pvc2 → pvc1
//   pvc3 → pvc1
//
// This means a pod using ANY sibling PVC is always patched to the current
// primary regardless of which direction the failover went.  The operation is
// fully idempotent: if the pod's volume already references the primary PVC it
// is simply absent from the remap table and left unchanged.
//
// Triggers (all event-driven, no polling):
//   • Controller startup  — CreateEvent for already-confirmed-primary VGR/VR
//   • Failover completes  — UpdateEvent when VGR/VR enters confirmed-primary
//   • New mirror PVC      — UpdateEvent when the confirmed-primary VGR's PVC
//                           list grows (VGR is updated by the VRC controller
//                           after each mirror PVC is provisioned)
//
// Patching:
//   • Managed workloads   — strategic-merge patch on pod-template volumes of
//                           the top-level owner (Deployment/StatefulSet/…)
//   • Standalone Pods     — delete + recreate with updated volume claim

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"go.uber.org/zap"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
)

// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch
// +kubebuilder:rbac:groups=apps,resources=deployments;statefulsets;daemonsets;replicasets,verbs=get;list;watch;update;patch

// Request-name prefixes used to route VSCR vs VVR events through a single queue.
const (
	vscrRemapPrefix = "vscr/"
	vvrRemapPrefix  = "vvr/"
)

// PVCRemapReconciler remaps Pod volumes to the new-primary mirror PVC after a
// failover on either a VastStorageClassReplication or VastVolumeReplication.
type PVCRemapReconciler struct {
	BaseReconciler
}

func (r *PVCRemapReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	name := req.Name
	ns := req.Namespace

	switch {
	case strings.HasPrefix(name, vscrRemapPrefix):
		return r.reconcileVSCR(ctx, strings.TrimPrefix(name, vscrRemapPrefix), ns)
	case strings.HasPrefix(name, vvrRemapPrefix):
		return r.reconcileVVR(ctx, strings.TrimPrefix(name, vvrRemapPrefix), ns)
	default:
		r.Log.Error("pvcremap: unexpected request name without type prefix, ignoring",
			zap.String("name", name))
		return ctrl.Result{}, nil
	}
}

// ---------------------------------------------------------------------------
// Per-type reconcile helpers
// ---------------------------------------------------------------------------

func (r *PVCRemapReconciler) reconcileVSCR(ctx context.Context, name, ns string) (ctrl.Result, error) {
	log := r.LogFor("pvc-remap", "vscr/"+ns+"/"+name)
	k8s := r.K8sFor(log)

	vscr, err := k8s.GetVastStorageClassReplication(ctx, name, ns)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}
	if !vscr.Spec.PVCRemap || vscr.GetDeletionTimestamp() != nil {
		return ctrl.Result{}, nil
	}

	newPrimary := vscr.Spec.PrimaryStorageClass

	vgr, err := k8s.GetVolumeGroupReplication(ctx, vgrNameForSC(name, newPrimary), ns)
	if k8serrors.IsNotFound(err) {
		return ctrl.Result{}, nil
	}
	if err != nil {
		return ctrl.Result{}, err
	}

	if vgr.Spec.ReplicationState != replicationv1alpha1.Primary ||
		vgr.Status.State != replicationv1alpha1.PrimaryState {
		return ctrl.Result{}, nil
	}

	// The VGR's PVC list contains the primary-cluster PVCs for this group.
	// Fetch each one by name (it's already in the informer cache by the time
	// confirmedPrimaryTransitionPredicate fires a VGR PVC list change event).
	pvcRefs := vgr.Status.PersistentVolumeClaimsRefList

	buildRemapTable := func(ctx context.Context) (map[string]string, error) {
		return buildSiblingRemapTable(ctx, k8s, ns, pvcRefs)
	}

	return doRemap(ctx, log, k8s, ns, buildRemapTable)
}

func (r *PVCRemapReconciler) reconcileVVR(ctx context.Context, name, ns string) (ctrl.Result, error) {
	log := r.LogFor("pvc-remap", "vvr/"+ns+"/"+name)
	k8s := r.K8sFor(log)

	vvr, err := k8s.GetVastVolumeReplication(ctx, name, ns)
	if err != nil {
		if k8serrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}
	if !vvr.Spec.PVCRemap || vvr.GetDeletionTimestamp() != nil {
		return ctrl.Result{}, nil
	}

	newPrimary := vvr.Spec.PrimaryStorageClass

	vr, err := k8s.GetVolumeReplication(ctx, vrNameForSC(name, newPrimary), ns)
	if k8serrors.IsNotFound(err) {
		return ctrl.Result{}, nil
	}
	if err != nil {
		return ctrl.Result{}, err
	}

	if vr.Spec.ReplicationState != replicationv1alpha1.Primary ||
		vr.Status.State != replicationv1alpha1.PrimaryState {
		return ctrl.Result{}, nil
	}

	// VolumeReplication has no PVC membership list.  Determine the primary PVC:
	//
	//   - If newPrimary has a managed mirror PVC (identified by LabelSourceVVR +
	//     LabelStorageClass), that PVC is the primary.
	//   - Otherwise the original source PVC (vvr.Spec.VolumeName) is primary
	//     (failback to the initial cluster).
	//
	// In both cases we then apply the same sibling-remap logic: every other
	// managed PVC with LabelSourcePVC == sourcePVCName is remapped to primary.
	sourcePVCName := vvr.Spec.VolumeName

	buildRemapTable := func(ctx context.Context) (map[string]string, error) {
		mirrors, err := k8s.ListPVCsByLabelSelector(ctx, ns, map[string]string{
			common.LabelManagedBy:    common.LabelManagedByValue,
			common.LabelStorageClass: newPrimary,
			common.LabelSourceVVR:    name,
		})
		if err != nil {
			return nil, fmt.Errorf("list primary mirror PVC for VVR %s: %w", name, err)
		}

		var primaryPVCName string
		if len(mirrors) > 0 {
			// Managed mirror PVC exists for the new primary SC.
			primaryPVCName = mirrors[0].Name
		} else {
			// No managed mirror → the original source PVC is primary (failback).
			primaryPVCName = sourcePVCName
		}

		// Build sibling remap table using LabelSourcePVC on managed PVCs.
		return buildSiblingRemapTable(ctx, k8s, ns, []corev1.LocalObjectReference{{Name: primaryPVCName}})
	}

	return doRemap(ctx, log, k8s, ns, buildRemapTable)
}

// ---------------------------------------------------------------------------
// Core remap logic (shared by VSCR and VVR paths)
// ---------------------------------------------------------------------------

// buildSiblingRemapTable constructs the remap table for a set of primary PVCs.
//
// For each primary PVC in primaryRefs:
//   - If it carries LabelSourcePVC → it is a managed mirror; the source PVC and
//     all other managed mirrors of that source are mapped → this primary PVC.
//   - If it has no LabelSourcePVC → it is the original source PVC (failback);
//     all managed mirrors of it are mapped → this primary PVC.
//
// The primary PVC itself is never added as a key (no no-op self-remaps).
func buildSiblingRemapTable(
	ctx context.Context,
	k8s *k8sclient.K8sClient,
	ns string,
	primaryRefs []corev1.LocalObjectReference,
) (map[string]string, error) {
	table := make(map[string]string)

	for _, ref := range primaryRefs {
		primaryPVC, err := k8s.GetPVC(ctx, ref.Name, ns)
		if k8serrors.IsNotFound(err) {
			continue // not yet in cache; next VGR PVC list change will retry
		}
		if err != nil {
			return nil, fmt.Errorf("get primary PVC %s: %w", ref.Name, err)
		}

		// sourcePVCName is the key shared by all siblings.
		sourcePVCName := primaryPVC.Labels[common.LabelSourcePVC]
		if sourcePVCName == "" {
			// No LabelSourcePVC → this IS the original source (failback).
			sourcePVCName = primaryPVC.Name
		}

		// Find all managed PVCs that are mirrors of this source.
		siblings, err := k8s.ListPVCsByLabelSelector(ctx, ns, map[string]string{
			common.LabelManagedBy: common.LabelManagedByValue,
			common.LabelSourcePVC: sourcePVCName,
		})
		if err != nil {
			return nil, fmt.Errorf("list sibling PVCs for source %s: %w", sourcePVCName, err)
		}
		for i := range siblings {
			if siblings[i].Name != primaryPVC.Name {
				table[siblings[i].Name] = primaryPVC.Name
			}
		}

		// When primaryPVC is itself a mirror, also remap the original source PVC.
		if primaryPVC.Labels[common.LabelSourcePVC] != "" {
			table[sourcePVCName] = primaryPVC.Name
		}
	}

	return table, nil
}

// doRemap applies the remap table to all Pods in the namespace.
//
// Idempotency is structural: pods already using the primary PVC are not present
// in the remap table and are left unchanged.  No annotations are written.
func doRemap(
	ctx context.Context,
	log *zap.Logger,
	k8s *k8sclient.K8sClient,
	namespace string,
	buildRemapTable func(ctx context.Context) (map[string]string, error),
) (ctrl.Result, error) {
	remapTable, err := buildRemapTable(ctx)
	if err != nil {
		return ctrl.Result{}, err
	}

	if len(remapTable) == 0 {
		log.Info("no pods need remapping; all already use the primary PVC or no siblings exist yet")
		return ctrl.Result{}, nil
	}

	log.Info("applying PVC remap", zap.Any("remapTable", remapTable))
	return ctrl.Result{}, remapPodsInNamespace(ctx, log, k8s, namespace, remapTable)
}

// ---------------------------------------------------------------------------
// Pod / workload patching
// ---------------------------------------------------------------------------

// remapPodsInNamespace scans all Pods in the namespace, finds those whose
// volumes reference old-primary PVCs, and patches their owning workload
// controller to use mirror PVCs instead.
func remapPodsInNamespace(
	ctx context.Context,
	log *zap.Logger,
	k8s *k8sclient.K8sClient,
	namespace string,
	remapTable map[string]string,
) error {
	podList := &corev1.PodList{}
	if err := k8s.Client().List(ctx, podList, client.InNamespace(namespace)); err != nil {
		return fmt.Errorf("list pods in namespace %s: %w", namespace, err)
	}

	// Track already-patched owners to avoid duplicate patches when multiple
	// pods belong to the same workload.
	patched := make(map[types.UID]struct{})

	for i := range podList.Items {
		pod := &podList.Items[i]

		needsRemap := volumesNeedingRemap(pod.Spec.Volumes, remapTable)
		if len(needsRemap) == 0 {
			continue
		}

		owner, err := topLevelOwner(ctx, k8s.Client(), pod)
		if err != nil {
			log.Warn("could not resolve owner for pod; skipping",
				zap.String("pod", pod.Name), zap.Error(err))
			continue
		}
		if owner == nil {
			log.Warn("pod has no owning workload controller; PVC remap requires a Deployment, StatefulSet, DaemonSet, or ReplicaSet — skipping",
				zap.String("pod", pod.Name))
			continue
		}

		if _, done := patched[owner.GetUID()]; done {
			continue
		}
		patched[owner.GetUID()] = struct{}{}

		if err := patchOwnerVolumes(ctx, k8s.Client(), owner, remapTable); err != nil {
			log.Error("failed to patch workload volumes",
				zap.String("kind", owner.GetObjectKind().GroupVersionKind().Kind),
				zap.String("name", owner.GetName()),
				zap.Error(err))
			continue
		}
		log.Info("patched workload pod-template volumes",
			zap.String("kind", owner.GetObjectKind().GroupVersionKind().Kind),
			zap.String("name", owner.GetName()),
			zap.Any("remapped", needsRemap))
	}
	return nil
}

// volumesNeedingRemap returns a map of volumeName → newClaimName for all
// volumes in the pod that reference an old-primary PVC in remapTable.
func volumesNeedingRemap(volumes []corev1.Volume, remapTable map[string]string) map[string]string {
	out := make(map[string]string)
	for _, v := range volumes {
		if v.PersistentVolumeClaim == nil {
			continue
		}
		if newName, ok := remapTable[v.PersistentVolumeClaim.ClaimName]; ok {
			out[v.Name] = newName
		}
	}
	return out
}

// topLevelOwner walks the Pod's owner chain and returns the top-level workload
// controller (Deployment, StatefulSet, DaemonSet, or standalone ReplicaSet).
// Returns nil for standalone Pods (no owning controller).
func topLevelOwner(ctx context.Context, c client.Client, pod *corev1.Pod) (client.Object, error) {
	ns := pod.Namespace
	for _, ref := range pod.OwnerReferences {
		if ref.Controller == nil || !*ref.Controller {
			continue
		}
		nn := types.NamespacedName{Name: ref.Name, Namespace: ns}
		switch ref.Kind {
		case "ReplicaSet":
			rs := &appsv1.ReplicaSet{}
			if err := c.Get(ctx, nn, rs); err != nil {
				return nil, err
			}
			// ReplicaSet is usually owned by a Deployment — ascend one level.
			for _, rsRef := range rs.OwnerReferences {
				if rsRef.Controller != nil && *rsRef.Controller && rsRef.Kind == "Deployment" {
					dep := &appsv1.Deployment{}
					if err := c.Get(ctx, types.NamespacedName{Name: rsRef.Name, Namespace: ns}, dep); err != nil {
						return nil, err
					}
					return dep, nil
				}
			}
			return rs, nil
		case "Deployment":
			dep := &appsv1.Deployment{}
			if err := c.Get(ctx, nn, dep); err != nil {
				return nil, err
			}
			return dep, nil
		case "StatefulSet":
			ss := &appsv1.StatefulSet{}
			if err := c.Get(ctx, nn, ss); err != nil {
				return nil, err
			}
			return ss, nil
		case "DaemonSet":
			ds := &appsv1.DaemonSet{}
			if err := c.Get(ctx, nn, ds); err != nil {
				return nil, err
			}
			return ds, nil
		}
	}
	return nil, nil // standalone pod
}

// patchOwnerVolumes issues a strategic-merge patch on the owning workload's
// pod-template volumes.  Only volumes present in remapTable are included in
// the patch payload; the API server merges by the `name` key and leaves all
// other volumes untouched.
func patchOwnerVolumes(
	ctx context.Context,
	c client.Client,
	owner client.Object,
	remapTable map[string]string,
) error {
	type pvcSource struct {
		ClaimName string `json:"claimName"`
	}
	type volumePatch struct {
		Name                  string     `json:"name"`
		PersistentVolumeClaim *pvcSource `json:"persistentVolumeClaim,omitempty"`
	}
	type podSpecPatch struct {
		Volumes []volumePatch `json:"volumes"`
	}
	type templatePatch struct {
		Spec podSpecPatch `json:"spec"`
	}
	type specPatch struct {
		Template templatePatch `json:"template"`
	}
	type workloadPatch struct {
		Spec specPatch `json:"spec"`
	}

	var templateVolumes []corev1.Volume
	switch o := owner.(type) {
	case *appsv1.Deployment:
		templateVolumes = o.Spec.Template.Spec.Volumes
	case *appsv1.StatefulSet:
		templateVolumes = o.Spec.Template.Spec.Volumes
	case *appsv1.DaemonSet:
		templateVolumes = o.Spec.Template.Spec.Volumes
	case *appsv1.ReplicaSet:
		templateVolumes = o.Spec.Template.Spec.Volumes
	default:
		return fmt.Errorf("unsupported owner kind %T", owner)
	}

	var toUpdate []volumePatch
	for _, v := range templateVolumes {
		if v.PersistentVolumeClaim == nil {
			continue
		}
		if newName, ok := remapTable[v.PersistentVolumeClaim.ClaimName]; ok {
			toUpdate = append(toUpdate, volumePatch{
				Name:                  v.Name,
				PersistentVolumeClaim: &pvcSource{ClaimName: newName},
			})
		}
	}
	if len(toUpdate) == 0 {
		return nil
	}

	payload, err := json.Marshal(workloadPatch{Spec: specPatch{Template: templatePatch{
		Spec: podSpecPatch{Volumes: toUpdate},
	}}})
	if err != nil {
		return fmt.Errorf("marshal volume patch: %w", err)
	}

	return c.Patch(ctx, owner, client.RawPatch(types.StrategicMergePatchType, payload))
}

// SetupPVCRemapController registers PVCRemapReconciler with the manager.
// It watches VolumeGroupReplication (VSCR-owned) and VolumeReplication
// (VVR-owned), both gated by confirmedPrimaryTransitionPredicate.
func SetupPVCRemapController(
	mgr ctrl.Manager,
	k8sClient *k8sclient.K8sClient,
	logger *zap.Logger,
	cfg *config.Config,
) error {
	base, err := NewBaseReconciler(mgr, k8sClient, logger, cfg, "pvcremap")
	if err != nil {
		return err
	}
	r := &PVCRemapReconciler{BaseReconciler: base}

	// VGR → enqueue "vscr/<owningVSCRName>"
	vgrMapper := handler.EnqueueRequestsFromMapFunc(
		func(_ context.Context, obj client.Object) []reconcile.Request {
			for _, ref := range obj.GetOwnerReferences() {
				if ref.Kind == "VastStorageClassReplication" {
					return []reconcile.Request{{NamespacedName: types.NamespacedName{
						Namespace: obj.GetNamespace(),
						Name:      vscrRemapPrefix + ref.Name,
					}}}
				}
			}
			return nil
		},
	)

	// VR → enqueue "vvr/<owningVVRName>"
	vrMapper := handler.EnqueueRequestsFromMapFunc(
		func(_ context.Context, obj client.Object) []reconcile.Request {
			for _, ref := range obj.GetOwnerReferences() {
				if ref.Kind == "VastVolumeReplication" {
					return []reconcile.Request{{NamespacedName: types.NamespacedName{
						Namespace: obj.GetNamespace(),
						Name:      vvrRemapPrefix + ref.Name,
					}}}
				}
			}
			return nil
		},
	)

	pred := confirmedPrimaryTransitionPredicate()

	return ctrl.NewControllerManagedBy(mgr).
		Named("pvcremap").
		Watches(&replicationv1alpha1.VolumeGroupReplication{}, vgrMapper,
			builder.WithPredicates(pred)).
		Watches(&replicationv1alpha1.VolumeReplication{}, vrMapper,
			builder.WithPredicates(pred)).
		Complete(r)
}
