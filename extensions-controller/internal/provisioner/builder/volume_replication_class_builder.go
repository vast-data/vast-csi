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
	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
)

// VolumeReplicationClassBuilder builds VolumeReplicationClass objects.
type VolumeReplicationClassBuilder struct {
	object *replicationv1alpha1.VolumeReplicationClass
}

// NewVolumeReplicationClass creates a new VolumeReplicationClassBuilder with a fresh VolumeReplicationClass.
func NewVolumeReplicationClass(name, namespace string) *VolumeReplicationClassBuilder {
	return &VolumeReplicationClassBuilder{
		object: &replicationv1alpha1.VolumeReplicationClass{
			TypeMeta: metav1.TypeMeta{
				APIVersion: replicationv1alpha1.GroupVersion.String(),
				Kind:       "VolumeReplicationClass",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
		},
	}
}

// Result returns the built VolumeReplicationClass.
func (b *VolumeReplicationClassBuilder) Result() *replicationv1alpha1.VolumeReplicationClass {
	return b.object
}

// WithName sets the VolumeReplicationClass's name.
func (b *VolumeReplicationClassBuilder) WithName(name string) *VolumeReplicationClassBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the VolumeReplicationClass's namespace.
func (b *VolumeReplicationClassBuilder) WithNamespace(namespace string) *VolumeReplicationClassBuilder {
	b.object.Namespace = namespace
	return b
}

// WithProvisioner sets the VolumeReplicationClass's provisioner.
func (b *VolumeReplicationClassBuilder) WithProvisioner(provisioner string) *VolumeReplicationClassBuilder {
	b.object.Spec.Provisioner = provisioner
	return b
}

// WithParameters sets the VolumeReplicationClass's parameters.
func (b *VolumeReplicationClassBuilder) WithParameters(params map[string]string) *VolumeReplicationClassBuilder {
	if b.object.Spec.Parameters == nil {
		b.object.Spec.Parameters = make(map[string]string)
	}
	for k, v := range params {
		b.object.Spec.Parameters[k] = v
	}
	return b
}

// WithParameter sets a single parameter on the VolumeReplicationClass.
func (b *VolumeReplicationClassBuilder) WithParameter(key, value string) *VolumeReplicationClassBuilder {
	if b.object.Spec.Parameters == nil {
		b.object.Spec.Parameters = make(map[string]string)
	}
	b.object.Spec.Parameters[key] = value
	return b
}

// WithLabelsMap sets the VolumeReplicationClass's labels from a map.
func (b *VolumeReplicationClassBuilder) WithLabelsMap(labels map[string]string) *VolumeReplicationClassBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *VolumeReplicationClassBuilder) WithManagedByLabel() *VolumeReplicationClassBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}
