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
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
)

// VolumeReplicationBuilder builds VolumeReplication objects.
// Error-prone methods (e.g. WithOwnerRef) defer their error; call Build()
// to retrieve the object together with any accumulated error.
type VolumeReplicationBuilder struct {
	object *replicationv1alpha1.VolumeReplication
	err    error
}

// ForVolumeReplication creates a new VolumeReplicationBuilder from an existing VolumeReplication.
// This is useful for modifying an existing VolumeReplication (e.g., for remote replication CRD creation).
func ForVolumeReplication(vr *replicationv1alpha1.VolumeReplication) *VolumeReplicationBuilder {
	// Deep copy to avoid modifying the original
	vrCopy := vr.DeepCopy()
	return &VolumeReplicationBuilder{
		object: vrCopy,
	}
}

// NewVolumeReplication creates a new VolumeReplicationBuilder with a fresh VolumeReplication.
func NewVolumeReplication(name, namespace string) *VolumeReplicationBuilder {
	return &VolumeReplicationBuilder{
		object: &replicationv1alpha1.VolumeReplication{
			TypeMeta: metav1.TypeMeta{
				APIVersion: replicationv1alpha1.GroupVersion.String(),
				Kind:       "VolumeReplication",
			},
			ObjectMeta: metav1.ObjectMeta{
				Name:      name,
				Namespace: namespace,
			},
		},
	}
}

// Result returns the built VolumeReplication.
func (b *VolumeReplicationBuilder) Result() *replicationv1alpha1.VolumeReplication {
	return b.object
}

// WithName sets the VolumeReplication's name.
func (b *VolumeReplicationBuilder) WithName(name string) *VolumeReplicationBuilder {
	b.object.Name = name
	return b
}

// WithNamespace sets the VolumeReplication's namespace.
func (b *VolumeReplicationBuilder) WithNamespace(namespace string) *VolumeReplicationBuilder {
	b.object.Namespace = namespace
	return b
}

// WithAnnotationsMap sets the VolumeReplication's annotations from a map.
func (b *VolumeReplicationBuilder) WithAnnotationsMap(annotations map[string]string) *VolumeReplicationBuilder {
	if b.object.Annotations == nil {
		b.object.Annotations = make(map[string]string)
	}
	for k, v := range annotations {
		b.object.Annotations[k] = v
	}
	return b
}

// ClearAnnotations removes all annotations from the VolumeReplication.
func (b *VolumeReplicationBuilder) ClearAnnotations() *VolumeReplicationBuilder {
	b.object.Annotations = nil
	return b
}

// WithoutAnnotations removes the specified annotation keys from the VolumeReplication.
func (b *VolumeReplicationBuilder) WithoutAnnotations(keys ...string) *VolumeReplicationBuilder {
	if b.object.Annotations == nil {
		return b
	}
	for _, key := range keys {
		delete(b.object.Annotations, key)
	}
	return b
}

// ClearLabels removes all labels from the VolumeReplication.
func (b *VolumeReplicationBuilder) ClearLabels() *VolumeReplicationBuilder {
	b.object.Labels = nil
	return b
}

// WithLabelsMap sets the VolumeReplication's labels from a map.
func (b *VolumeReplicationBuilder) WithLabelsMap(labels map[string]string) *VolumeReplicationBuilder {
	if b.object.Labels == nil {
		b.object.Labels = make(map[string]string)
	}
	for k, v := range labels {
		b.object.Labels[k] = v
	}
	return b
}

// WithManagedByLabel sets the managed-by label to indicate this resource is managed by the extensions controller.
func (b *VolumeReplicationBuilder) WithManagedByLabel() *VolumeReplicationBuilder {
	return b.WithLabelsMap(map[string]string{
		common.LabelManagedBy: common.LabelManagedByValue,
	})
}

// ClearFinalizers removes all finalizers from the VolumeReplication.
func (b *VolumeReplicationBuilder) ClearFinalizers() *VolumeReplicationBuilder {
	b.object.Finalizers = nil
	return b
}

// WithFinalizers sets the VolumeReplication's finalizers.
func (b *VolumeReplicationBuilder) WithFinalizers(finalizers ...string) *VolumeReplicationBuilder {
	b.object.Finalizers = finalizers
	return b
}

// WithoutResourceVersion removes the resourceVersion from the VolumeReplication.
func (b *VolumeReplicationBuilder) WithoutResourceVersion() *VolumeReplicationBuilder {
	b.object.ResourceVersion = ""
	return b
}

// WithoutUID removes the UID from the VolumeReplication.
func (b *VolumeReplicationBuilder) WithoutUID() *VolumeReplicationBuilder {
	b.object.UID = ""
	return b
}

// WithoutCreationTimestamp removes the creationTimestamp from the VolumeReplication.
func (b *VolumeReplicationBuilder) WithoutCreationTimestamp() *VolumeReplicationBuilder {
	b.object.CreationTimestamp = metav1.Time{}
	return b
}

// ClearStatus removes all status fields from the VolumeReplication.
func (b *VolumeReplicationBuilder) ClearStatus() *VolumeReplicationBuilder {
	b.object.Status = replicationv1alpha1.VolumeReplicationStatus{}
	return b
}

// WithReplicationState sets the VolumeReplication's replication state.
func (b *VolumeReplicationBuilder) WithReplicationState(state replicationv1alpha1.ReplicationState) *VolumeReplicationBuilder {
	b.object.Spec.ReplicationState = state
	return b
}

// WithVolumeReplicationClass sets the VolumeReplication's volume replication class.
func (b *VolumeReplicationBuilder) WithVolumeReplicationClass(className string) *VolumeReplicationBuilder {
	b.object.Spec.VolumeReplicationClass = className
	return b
}

// WithDataSource sets the VolumeReplication's data source to a PVC.
func (b *VolumeReplicationBuilder) WithDataSource(pvcName string) *VolumeReplicationBuilder {
	b.object.Spec.DataSource = corev1.TypedLocalObjectReference{
		Kind: "PersistentVolumeClaim",
		Name: pvcName,
	}
	return b
}

// WithAutoResync sets the VolumeReplication's auto resync flag.
func (b *VolumeReplicationBuilder) WithAutoResync(autoResync bool) *VolumeReplicationBuilder {
	b.object.Spec.AutoResync = autoResync
	return b
}

// WithReplicationHandle sets the VolumeReplication's replication handle.
func (b *VolumeReplicationBuilder) WithReplicationHandle(handle string) *VolumeReplicationBuilder {
	b.object.Spec.ReplicationHandle = handle
	return b
}

// WithOwnerRef sets a controller owner reference on the VolumeReplication so that
// Kubernetes GC cascades deletion from the owner to this object.
// Any error is deferred and returned by Build().
func (b *VolumeReplicationBuilder) WithOwnerRef(owner client.Object, scheme *runtime.Scheme) *VolumeReplicationBuilder {
	if b.err != nil {
		return b
	}
	if err := controllerutil.SetControllerReference(owner, b.object, scheme); err != nil {
		b.err = fmt.Errorf("failed to set controller reference on VolumeReplication %q: %w",
			b.object.Name, err)
	}
	return b
}

// Build returns the constructed VolumeReplication together with any error
// accumulated by error-prone builder methods such as WithOwnerRef.
func (b *VolumeReplicationBuilder) Build() (*replicationv1alpha1.VolumeReplication, error) {
	return b.object, b.err
}
