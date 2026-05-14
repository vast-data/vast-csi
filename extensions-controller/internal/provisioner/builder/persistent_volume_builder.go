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

package builder

import (
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
)

// PersistentVolumeBuilder builds PersistentVolume objects.
type PersistentVolumeBuilder struct {
	object *corev1.PersistentVolume
}

// ForPersistentVolume creates a new PersistentVolumeBuilder from an existing PV.
// This is useful for modifying an existing PV (e.g., for static provisioning).
func ForPersistentVolume(pv *corev1.PersistentVolume) *PersistentVolumeBuilder {
	// Deep copy to avoid modifying the original
	pvCopy := pv.DeepCopy()
	return &PersistentVolumeBuilder{
		object: pvCopy,
	}
}

// NewPersistentVolume creates a new PersistentVolumeBuilder with a fresh PV.
func NewPersistentVolume(name string) *PersistentVolumeBuilder {
	return &PersistentVolumeBuilder{
		object: &corev1.PersistentVolume{
			TypeMeta: metav1.TypeMeta{
				APIVersion: corev1.SchemeGroupVersion.String(),
				Kind:       "PersistentVolume",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name: name,
			},
		},
	}
}

// Result returns the built PersistentVolume.
func (b *PersistentVolumeBuilder) Result() *corev1.PersistentVolume {
	return b.object
}

// ObjectMeta applies functional options to the PersistentVolume's ObjectMeta.
func (b *PersistentVolumeBuilder) ObjectMeta(opts ...ObjectMetaOpt) *PersistentVolumeBuilder {
	for _, opt := range opts {
		opt(b.object)
	}
	return b
}

// WithName sets the PersistentVolume's name.
func (b *PersistentVolumeBuilder) WithName(name string) *PersistentVolumeBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the PersistentVolume's namespace.
func (b *PersistentVolumeBuilder) WithNamespace(namespace string) *PersistentVolumeBuilder {
	b.object.Namespace = namespace
	return b
}

// WithAnnotationsMap sets the PersistentVolume's annotations from a map.
func (b *PersistentVolumeBuilder) WithAnnotationsMap(annotations map[string]string) *PersistentVolumeBuilder {
	if b.object.Annotations == nil {
		b.object.Annotations = make(map[string]string)
	}
	for k, v := range annotations {
		b.object.Annotations[k] = v
	}
	return b
}

// ClearAnnotations removes all annotations from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearAnnotations() *PersistentVolumeBuilder {
	b.object.Annotations = nil
	return b
}

// WithoutAnnotations removes the specified annotation keys from the PersistentVolume.
func (b *PersistentVolumeBuilder) WithoutAnnotations(keys ...string) *PersistentVolumeBuilder {
	if b.object.Annotations == nil {
		return b
	}
	for _, key := range keys {
		delete(b.object.Annotations, key)
	}
	return b
}

// ClearLabels removes all labels from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearLabels() *PersistentVolumeBuilder {
	b.object.Labels = nil
	return b
}

// WithLabelsMap sets the PersistentVolume's labels from a map.
func (b *PersistentVolumeBuilder) WithLabelsMap(labels map[string]string) *PersistentVolumeBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *PersistentVolumeBuilder) WithManagedByLabel() *PersistentVolumeBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}

// ClearFinalizers removes all finalizers from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearFinalizers() *PersistentVolumeBuilder {
	b.object.Finalizers = nil
	return b
}

// WithFinalizers sets the PersistentVolume's finalizers.
func (b *PersistentVolumeBuilder) WithFinalizers(finalizers ...string) *PersistentVolumeBuilder {
	b.object.Finalizers = finalizers
	return b
}

// WithoutResourceVersion removes the resourceVersion from the PersistentVolume.
func (b *PersistentVolumeBuilder) WithoutResourceVersion() *PersistentVolumeBuilder {
	b.object.ResourceVersion = ""
	return b
}

// WithoutUID removes the UID from the PersistentVolume.
func (b *PersistentVolumeBuilder) WithoutUID() *PersistentVolumeBuilder {
	b.object.UID = ""
	return b
}

// WithStorageClass sets the PersistentVolume's storage class name.
func (b *PersistentVolumeBuilder) WithStorageClass(name string) *PersistentVolumeBuilder {
	b.object.Spec.StorageClassName = name
	return b
}

// WithClaimRef sets the PersistentVolume's claim ref.
func (b *PersistentVolumeBuilder) WithClaimRef(ns, name string) *PersistentVolumeBuilder {
	b.object.Spec.ClaimRef = &corev1.ObjectReference{
		Namespace: ns,
		Name:      name,
	}
	return b
}

// ClearClaimRef removes the claim ref from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearClaimRef() *PersistentVolumeBuilder {
	b.object.Spec.ClaimRef = nil
	return b
}

// WithVolumeHandle sets the PersistentVolume's volume handle.
func (b *PersistentVolumeBuilder) WithVolumeHandle(volumeHandle string) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.VolumeHandle = volumeHandle
	return b
}

// WithCSIDriver sets the PersistentVolume's CSI driver.
func (b *PersistentVolumeBuilder) WithCSIDriver(driver string) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.Driver = driver
	return b
}

// WithVolumeAttributes sets the PersistentVolume's CSI volume attributes.
func (b *PersistentVolumeBuilder) WithVolumeAttributes(attrs map[string]string) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	if b.object.Spec.CSI.VolumeAttributes == nil {
		b.object.Spec.CSI.VolumeAttributes = make(map[string]string)
	}
	for k, v := range attrs {
		b.object.Spec.CSI.VolumeAttributes[k] = v
	}
	return b
}

// ClearVolumeAttributes removes all volume attributes from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearVolumeAttributes() *PersistentVolumeBuilder {
	if b.object.Spec.CSI != nil {
		b.object.Spec.CSI.VolumeAttributes = nil
	}
	return b
}

// WithoutVolumeAttribute removes a specific volume attribute by key.
func (b *PersistentVolumeBuilder) WithoutVolumeAttribute(key string) *PersistentVolumeBuilder {
	if b.object.Spec.CSI != nil && b.object.Spec.CSI.VolumeAttributes != nil {
		delete(b.object.Spec.CSI.VolumeAttributes, key)
	}
	return b
}

// WithReclaimPolicy sets the PersistentVolume's reclaim policy.
func (b *PersistentVolumeBuilder) WithReclaimPolicy(policy corev1.PersistentVolumeReclaimPolicy) *PersistentVolumeBuilder {
	b.object.Spec.PersistentVolumeReclaimPolicy = policy
	return b
}

// WithVolumeMode sets the PersistentVolume's volume mode.
func (b *PersistentVolumeBuilder) WithVolumeMode(volMode corev1.PersistentVolumeMode) *PersistentVolumeBuilder {
	b.object.Spec.VolumeMode = &volMode
	return b
}

// WithAccessModes sets the PersistentVolume's access modes.
func (b *PersistentVolumeBuilder) WithAccessModes(modes ...corev1.PersistentVolumeAccessMode) *PersistentVolumeBuilder {
	b.object.Spec.AccessModes = modes
	return b
}

// WithCapacity sets the PersistentVolume's capacity.
func (b *PersistentVolumeBuilder) WithCapacity(capacity corev1.ResourceList) *PersistentVolumeBuilder {
	b.object.Spec.Capacity = capacity
	return b
}

// WithControllerPublishSecretRef sets the PersistentVolume's CSI controller publish secret reference.
func (b *PersistentVolumeBuilder) WithControllerPublishSecretRef(secretRef *corev1.SecretReference) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.ControllerPublishSecretRef = secretRef
	return b
}

// WithNodeStageSecretRef sets the PersistentVolume's CSI node stage secret reference.
func (b *PersistentVolumeBuilder) WithNodeStageSecretRef(secretRef *corev1.SecretReference) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.NodeStageSecretRef = secretRef
	return b
}

// WithNodePublishSecretRef sets the PersistentVolume's CSI node publish secret reference.
func (b *PersistentVolumeBuilder) WithNodePublishSecretRef(secretRef *corev1.SecretReference) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.NodePublishSecretRef = secretRef
	return b
}

// WithControllerExpandSecretRef sets the PersistentVolume's CSI controller expand secret reference.
func (b *PersistentVolumeBuilder) WithControllerExpandSecretRef(secretRef *corev1.SecretReference) *PersistentVolumeBuilder {
	if b.object.Spec.CSI == nil {
		b.object.Spec.CSI = &corev1.CSIPersistentVolumeSource{}
	}
	b.object.Spec.CSI.ControllerExpandSecretRef = secretRef
	return b
}

// ClearStatus removes all status fields from the PersistentVolume.
func (b *PersistentVolumeBuilder) ClearStatus() *PersistentVolumeBuilder {
	b.object.Status = corev1.PersistentVolumeStatus{}
	return b
}

// Phase sets the PersistentVolume's phase.
func (b *PersistentVolumeBuilder) Phase(phase corev1.PersistentVolumePhase) *PersistentVolumeBuilder {
	if b.object.Status.Phase == "" {
		b.object.Status = corev1.PersistentVolumeStatus{}
	}
	b.object.Status.Phase = phase
	return b
}
