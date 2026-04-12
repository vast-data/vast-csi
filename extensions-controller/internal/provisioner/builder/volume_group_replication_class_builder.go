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

// VolumeGroupReplicationClassBuilder builds VolumeGroupReplicationClass objects.
type VolumeGroupReplicationClassBuilder struct {
	object *replicationv1alpha1.VolumeGroupReplicationClass
}

// NewVolumeGroupReplicationClass creates a new VolumeGroupReplicationClassBuilder with a fresh VolumeGroupReplicationClass.
func NewVolumeGroupReplicationClass(name, namespace string) *VolumeGroupReplicationClassBuilder {
	return &VolumeGroupReplicationClassBuilder{
		object: &replicationv1alpha1.VolumeGroupReplicationClass{
			TypeMeta: metav1.TypeMeta{
				APIVersion: replicationv1alpha1.GroupVersion.String(),
				Kind:       "VolumeGroupReplicationClass",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
		},
	}
}

// Result returns the built VolumeGroupReplicationClass.
func (b *VolumeGroupReplicationClassBuilder) Result() *replicationv1alpha1.VolumeGroupReplicationClass {
	return b.object
}

// WithName sets the VolumeGroupReplicationClass's name.
func (b *VolumeGroupReplicationClassBuilder) WithName(name string) *VolumeGroupReplicationClassBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the VolumeGroupReplicationClass's namespace.
func (b *VolumeGroupReplicationClassBuilder) WithNamespace(namespace string) *VolumeGroupReplicationClassBuilder {
	b.object.Namespace = namespace
	return b
}

// WithProvisioner sets the VolumeGroupReplicationClass's provisioner.
func (b *VolumeGroupReplicationClassBuilder) WithProvisioner(provisioner string) *VolumeGroupReplicationClassBuilder {
	b.object.Spec.Provisioner = provisioner
	return b
}

// WithParameters sets the VolumeGroupReplicationClass's parameters.
func (b *VolumeGroupReplicationClassBuilder) WithParameters(params map[string]string) *VolumeGroupReplicationClassBuilder {
	if b.object.Spec.Parameters == nil {
		b.object.Spec.Parameters = make(map[string]string)
	}
	for k, v := range params {
		b.object.Spec.Parameters[k] = v
	}
	return b
}

// WithParameter sets a single parameter on the VolumeGroupReplicationClass.
func (b *VolumeGroupReplicationClassBuilder) WithParameter(key, value string) *VolumeGroupReplicationClassBuilder {
	if b.object.Spec.Parameters == nil {
		b.object.Spec.Parameters = make(map[string]string)
	}
	b.object.Spec.Parameters[key] = value
	return b
}

// WithLabelsMap sets the VolumeGroupReplicationClass's labels from a map.
func (b *VolumeGroupReplicationClassBuilder) WithLabelsMap(labels map[string]string) *VolumeGroupReplicationClassBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *VolumeGroupReplicationClassBuilder) WithManagedByLabel() *VolumeGroupReplicationClassBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}
