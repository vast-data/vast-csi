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
	"fmt"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
)

// VolumeGroupReplicationBuilder builds VolumeGroupReplication objects.
// Error-prone methods (e.g. WithOwnerRef) defer their error; call Build()
// to retrieve the object together with any accumulated error.
type VolumeGroupReplicationBuilder struct {
	object *replicationv1alpha1.VolumeGroupReplication
	err    error
}

// ForVolumeGroupReplication creates a new VolumeGroupReplicationBuilder from an existing VolumeGroupReplication.
// This is useful for modifying an existing VolumeGroupReplication (e.g., for remote replication CRD creation).
func ForVolumeGroupReplication(vgr *replicationv1alpha1.VolumeGroupReplication) *VolumeGroupReplicationBuilder {
	// Deep copy to avoid modifying the original
	vgrCopy := vgr.DeepCopy()
	return &VolumeGroupReplicationBuilder{
		object: vgrCopy,
	}
}

// NewVolumeGroupReplication creates a new VolumeGroupReplicationBuilder with a fresh VolumeGroupReplication.
func NewVolumeGroupReplication(name, namespace string) *VolumeGroupReplicationBuilder {
	return &VolumeGroupReplicationBuilder{
		object: &replicationv1alpha1.VolumeGroupReplication{
			TypeMeta: metav1.TypeMeta{
				APIVersion: replicationv1alpha1.GroupVersion.String(),
				Kind:       "VolumeGroupReplication",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
		},
	}
}

// Result returns the built VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) Result() *replicationv1alpha1.VolumeGroupReplication {
	return b.object
}

// WithName sets the VolumeGroupReplication's name.
func (b *VolumeGroupReplicationBuilder) WithName(name string) *VolumeGroupReplicationBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the VolumeGroupReplication's namespace.
func (b *VolumeGroupReplicationBuilder) WithNamespace(namespace string) *VolumeGroupReplicationBuilder {
	b.object.Namespace = namespace
	return b
}

// WithAnnotationsMap sets the VolumeGroupReplication's annotations from a map.
func (b *VolumeGroupReplicationBuilder) WithAnnotationsMap(annotations map[string]string) *VolumeGroupReplicationBuilder {
	if b.object.Annotations == nil {
		b.object.Annotations = make(map[string]string)
	}
	for k, v := range annotations {
		b.object.Annotations[k] = v
	}
	return b
}

// ClearAnnotations removes all annotations from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) ClearAnnotations() *VolumeGroupReplicationBuilder {
	b.object.Annotations = nil
	return b
}

// WithoutAnnotations removes the specified annotation keys from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) WithoutAnnotations(keys ...string) *VolumeGroupReplicationBuilder {
	if b.object.Annotations == nil {
		return b
	}
	for _, key := range keys {
		delete(b.object.Annotations, key)
	}
	return b
}

// ClearLabels removes all labels from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) ClearLabels() *VolumeGroupReplicationBuilder {
	b.object.Labels = nil
	return b
}

// WithLabelsMap sets the VolumeGroupReplication's labels from a map.
func (b *VolumeGroupReplicationBuilder) WithLabelsMap(labels map[string]string) *VolumeGroupReplicationBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *VolumeGroupReplicationBuilder) WithManagedByLabel() *VolumeGroupReplicationBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}

// ClearFinalizers removes all finalizers from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) ClearFinalizers() *VolumeGroupReplicationBuilder {
	b.object.Finalizers = nil
	return b
}

// WithFinalizers sets the VolumeGroupReplication's finalizers.
func (b *VolumeGroupReplicationBuilder) WithFinalizers(finalizers ...string) *VolumeGroupReplicationBuilder {
	b.object.Finalizers = finalizers
	return b
}

// WithoutResourceVersion removes the resourceVersion from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) WithoutResourceVersion() *VolumeGroupReplicationBuilder {
	b.object.ResourceVersion = ""
	return b
}

// WithoutUID removes the UID from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) WithoutUID() *VolumeGroupReplicationBuilder {
	b.object.UID = ""
	return b
}

// WithoutCreationTimestamp removes the creationTimestamp from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) WithoutCreationTimestamp() *VolumeGroupReplicationBuilder {
	b.object.CreationTimestamp = metav1.Time{}
	return b
}

// ClearStatus removes all status fields from the VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) ClearStatus() *VolumeGroupReplicationBuilder {
	b.object.Status = replicationv1alpha1.VolumeGroupReplicationStatus{}
	return b
}

// WithReplicationState sets the VolumeGroupReplication's replication state.
func (b *VolumeGroupReplicationBuilder) WithReplicationState(state replicationv1alpha1.ReplicationState) *VolumeGroupReplicationBuilder {
	b.object.Spec.ReplicationState = state
	return b
}

// WithVolumeGroupReplicationClassName sets the VolumeGroupReplication's volume group replication class name.
func (b *VolumeGroupReplicationBuilder) WithVolumeGroupReplicationClassName(className string) *VolumeGroupReplicationBuilder {
	b.object.Spec.VolumeGroupReplicationClassName = className
	return b
}

// WithVolumeReplicationClassName sets the VolumeGroupReplication's volume replication class name.
func (b *VolumeGroupReplicationBuilder) WithVolumeReplicationClassName(className string) *VolumeGroupReplicationBuilder {
	b.object.Spec.VolumeReplicationClassName = className
	return b
}

// WithSource sets the VolumeGroupReplication's source selector.
func (b *VolumeGroupReplicationBuilder) WithSource(selector *metav1.LabelSelector) *VolumeGroupReplicationBuilder {
	b.object.Spec.Source = replicationv1alpha1.VolumeGroupReplicationSource{
		Selector: selector,
	}
	return b
}

// WithSourceMatchLabels sets the VolumeGroupReplication's source selector match labels.
func (b *VolumeGroupReplicationBuilder) WithSourceMatchLabels(labels map[string]string) *VolumeGroupReplicationBuilder {
	if b.object.Spec.Source.Selector == nil {
		b.object.Spec.Source.Selector = &metav1.LabelSelector{}
	}
	if b.object.Spec.Source.Selector.MatchLabels == nil {
		b.object.Spec.Source.Selector.MatchLabels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Spec.Source.Selector.MatchLabels[k] = v
	}
	return b
}

// WithAutoResync sets the VolumeGroupReplication's auto resync flag.
func (b *VolumeGroupReplicationBuilder) WithAutoResync(autoResync bool) *VolumeGroupReplicationBuilder {
	b.object.Spec.AutoResync = autoResync
	return b
}

// WithoutVolumeReplicationName removes the volumeReplicationName field from the VolumeGroupReplication spec.
func (b *VolumeGroupReplicationBuilder) WithoutVolumeReplicationName() *VolumeGroupReplicationBuilder {
	b.object.Spec.VolumeReplicationName = ""
	return b
}

// WithoutVolumeGroupReplicationContentName removes the volumeGroupReplicationContentName field from the VolumeGroupReplication spec.
func (b *VolumeGroupReplicationBuilder) WithoutVolumeGroupReplicationContentName() *VolumeGroupReplicationBuilder {
	b.object.Spec.VolumeGroupReplicationContentName = ""
	return b
}

// WithoutExternal removes the external field from the VolumeGroupReplication spec.
func (b *VolumeGroupReplicationBuilder) WithoutExternal() *VolumeGroupReplicationBuilder {
	b.object.Spec.External = false
	return b
}

// ClearSpecFields removes all unwanted fields from the spec, keeping only essential ones.
// This is used when creating a clean destination VolumeGroupReplication.
func (b *VolumeGroupReplicationBuilder) ClearSpecFields() *VolumeGroupReplicationBuilder {
	b.object.Spec.VolumeReplicationName = ""
	b.object.Spec.VolumeGroupReplicationContentName = ""
	b.object.Spec.External = false
	return b
}

// WithOwnerRef sets a controller owner reference on the VolumeGroupReplication so that
// Kubernetes GC cascades deletion from the owner to this object.
// Any error is deferred and returned by Build().
func (b *VolumeGroupReplicationBuilder) WithOwnerRef(owner client.Object, scheme *runtime.Scheme) *VolumeGroupReplicationBuilder {
	if b.err != nil {
		return b
	}
	if err := controllerutil.SetControllerReference(owner, b.object, scheme); err != nil {
		b.err = fmt.Errorf("failed to set controller reference on VolumeGroupReplication %q: %w",
			b.object.Name, err)
	}
	return b
}

// Build returns the constructed VolumeGroupReplication together with any error
// accumulated by error-prone builder methods such as WithOwnerRef.
// Prefer Build() over Result() whenever those methods are used.
func (b *VolumeGroupReplicationBuilder) Build() (*replicationv1alpha1.VolumeGroupReplication, error) {
	return b.object, b.err
}
