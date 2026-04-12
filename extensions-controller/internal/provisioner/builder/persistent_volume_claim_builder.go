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

// PersistentVolumeClaimBuilder builds PersistentVolumeClaim objects.
type PersistentVolumeClaimBuilder struct {
	object *corev1.PersistentVolumeClaim
}

// ForPersistentVolumeClaim creates a new PersistentVolumeClaimBuilder from an existing PVC.
// This is useful for modifying an existing PVC (e.g., for static provisioning).
func ForPersistentVolumeClaim(pvc *corev1.PersistentVolumeClaim) *PersistentVolumeClaimBuilder {
	// Deep copy to avoid modifying the original
	pvcCopy := pvc.DeepCopy()
	return &PersistentVolumeClaimBuilder{
		object: pvcCopy,
	}
}

// NewPersistentVolumeClaim creates a new PersistentVolumeClaimBuilder with a fresh PVC.
func NewPersistentVolumeClaim(ns, name string) *PersistentVolumeClaimBuilder {
	return &PersistentVolumeClaimBuilder{
		object: &corev1.PersistentVolumeClaim{
			TypeMeta: metav1.TypeMeta{
				APIVersion: corev1.SchemeGroupVersion.String(),
				Kind:       "PersistentVolumeClaim",
			},
			ObjectMeta: metav1.ObjectMeta{
				Namespace: ns,
				Name:      name,
			},
		},
	}
}

// Result returns the built PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) Result() *corev1.PersistentVolumeClaim {
	return b.object
}

// ObjectMeta applies functional options to the PersistentVolumeClaim's ObjectMeta.
func (b *PersistentVolumeClaimBuilder) ObjectMeta(opts ...ObjectMetaOpt) *PersistentVolumeClaimBuilder {
	for _, opt := range opts {
		opt(b.object)
	}
	return b
}

// WithName sets the PersistentVolumeClaim's name.
func (b *PersistentVolumeClaimBuilder) WithName(name string) *PersistentVolumeClaimBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the PersistentVolumeClaim's namespace.
func (b *PersistentVolumeClaimBuilder) WithNamespace(namespace string) *PersistentVolumeClaimBuilder {
	b.object.Namespace = namespace
	return b
}

// WithAnnotationsMap sets the PersistentVolumeClaim's annotations from a map.
func (b *PersistentVolumeClaimBuilder) WithAnnotationsMap(annotations map[string]string) *PersistentVolumeClaimBuilder {
	if b.object.Annotations == nil {
		b.object.Annotations = make(map[string]string)
	}
	for k, v := range annotations {
		b.object.Annotations[k] = v
	}
	return b
}

// ClearAnnotations removes all annotations from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) ClearAnnotations() *PersistentVolumeClaimBuilder {
	b.object.Annotations = nil
	return b
}

// WithoutAnnotations removes the specified annotation keys from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) WithoutAnnotations(keys ...string) *PersistentVolumeClaimBuilder {
	if b.object.Annotations == nil {
		return b
	}
	for _, key := range keys {
		delete(b.object.Annotations, key)
	}
	return b
}

// ClearLabels removes all labels from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) ClearLabels() *PersistentVolumeClaimBuilder {
	b.object.Labels = nil
	return b
}

// WithLabelsMap sets the PersistentVolumeClaim's labels from a map.
func (b *PersistentVolumeClaimBuilder) WithLabelsMap(labels map[string]string) *PersistentVolumeClaimBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *PersistentVolumeClaimBuilder) WithManagedByLabel() *PersistentVolumeClaimBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}

// ClearFinalizers removes all finalizers from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) ClearFinalizers() *PersistentVolumeClaimBuilder {
	b.object.Finalizers = nil
	return b
}

// WithFinalizers sets the PersistentVolumeClaim's finalizers.
func (b *PersistentVolumeClaimBuilder) WithFinalizers(finalizers ...string) *PersistentVolumeClaimBuilder {
	b.object.Finalizers = finalizers
	return b
}

// WithoutResourceVersion removes the resourceVersion from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) WithoutResourceVersion() *PersistentVolumeClaimBuilder {
	b.object.ResourceVersion = ""
	return b
}

// WithoutUID removes the UID from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) WithoutUID() *PersistentVolumeClaimBuilder {
	b.object.UID = ""
	return b
}

// WithVolumeName sets the PersistentVolumeClaim's volume name.
func (b *PersistentVolumeClaimBuilder) WithVolumeName(name string) *PersistentVolumeClaimBuilder {
	b.object.Spec.VolumeName = name
	return b
}

// WithStorageClass sets the PersistentVolumeClaim's storage class name.
func (b *PersistentVolumeClaimBuilder) WithStorageClass(name string) *PersistentVolumeClaimBuilder {
	if name == "" {
		b.object.Spec.StorageClassName = nil
	} else {
		b.object.Spec.StorageClassName = &name
	}
	return b
}

// ClearStatus removes all status fields from the PersistentVolumeClaim.
func (b *PersistentVolumeClaimBuilder) ClearStatus() *PersistentVolumeClaimBuilder {
	b.object.Status = corev1.PersistentVolumeClaimStatus{}
	return b
}

// WithPhase sets the PersistentVolumeClaim's status Phase.
func (b *PersistentVolumeClaimBuilder) WithPhase(phase corev1.PersistentVolumeClaimPhase) *PersistentVolumeClaimBuilder {
	if b.object.Status.Phase == "" {
		b.object.Status = corev1.PersistentVolumeClaimStatus{}
	}
	b.object.Status.Phase = phase
	return b
}

// WithAccessModes sets the PersistentVolumeClaim's access modes.
func (b *PersistentVolumeClaimBuilder) WithAccessModes(modes ...corev1.PersistentVolumeAccessMode) *PersistentVolumeClaimBuilder {
	b.object.Spec.AccessModes = modes
	return b
}

// WithResources sets the PersistentVolumeClaim's resource requirements.
func (b *PersistentVolumeClaimBuilder) WithResources(requests corev1.ResourceList) *PersistentVolumeClaimBuilder {
	if b.object.Spec.Resources.Requests == nil {
		b.object.Spec.Resources.Requests = make(corev1.ResourceList)
	}
	b.object.Spec.Resources.Requests = requests
	return b
}
