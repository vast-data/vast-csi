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
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// ObjectMetaOpt is a functional option for ObjectMeta.
type ObjectMetaOpt func(metav1.Object)

// WithName is a functional option that applies the specified name to an object.
func WithName(val string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetName(val)
	}
}

// WithNamespace is a functional option that applies the specified namespace to an object.
func WithNamespace(val string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetNamespace(val)
	}
}

// WithLabels is a functional option that applies the specified label keys/values to an object.
// Values are provided as key-value pairs: WithLabels("key1", "value1", "key2", "value2")
func WithLabels(vals ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetLabels(setMapEntries(obj.GetLabels(), vals...))
	}
}

// WithLabelsMap is a functional option that applies the specified labels map to an object.
func WithLabelsMap(labels map[string]string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		objLabels := obj.GetLabels()
		if objLabels == nil {
			objLabels = make(map[string]string)
		}

		// If the label already exists in the object, it will be overwritten
		for k, v := range labels {
			objLabels[k] = v
		}

		obj.SetLabels(objLabels)
	}
}

// WithAnnotations is a functional option that applies the specified annotation keys/values to an object.
// Values are provided as key-value pairs: WithAnnotations("key1", "value1", "key2", "value2")
func WithAnnotations(vals ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetAnnotations(setMapEntries(obj.GetAnnotations(), vals...))
	}
}

// WithAnnotationsMap is a functional option that applies the specified annotations map to an object.
func WithAnnotationsMap(annotations map[string]string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		objAnnotations := obj.GetAnnotations()
		if objAnnotations == nil {
			objAnnotations = make(map[string]string)
		}

		// If the annotation already exists in the object, it will be overwritten
		for k, v := range annotations {
			objAnnotations[k] = v
		}

		obj.SetAnnotations(objAnnotations)
	}
}

// WithoutAnnotations removes the specified annotation keys from an object.
func WithoutAnnotations(keys ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		annotations := obj.GetAnnotations()
		if annotations == nil {
			return
		}

		for _, key := range keys {
			delete(annotations, key)
		}

		obj.SetAnnotations(annotations)
	}
}

// ClearAnnotations removes all annotations from an object.
func ClearAnnotations() ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetAnnotations(nil)
	}
}

// ClearLabels removes all labels from an object.
func ClearLabels() ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetLabels(nil)
	}
}

// WithFinalizers is a functional option that sets the specified finalizers on an object.
// This replaces all existing finalizers.
func WithFinalizers(vals ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetFinalizers(vals)
	}
}

// AddFinalizers adds the specified finalizers to an object without removing existing ones.
func AddFinalizers(vals ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		existing := obj.GetFinalizers()
		finalizerMap := make(map[string]bool)
		for _, f := range existing {
			finalizerMap[f] = true
		}
		for _, f := range vals {
			finalizerMap[f] = true
		}

		finalizers := make([]string, 0, len(finalizerMap))
		for f := range finalizerMap {
			finalizers = append(finalizers, f)
		}
		obj.SetFinalizers(finalizers)
	}
}

// WithoutFinalizers removes the specified finalizers from an object.
func WithoutFinalizers(vals ...string) ObjectMetaOpt {
	return func(obj metav1.Object) {
		existing := obj.GetFinalizers()
		if len(existing) == 0 {
			return
		}

		removeMap := make(map[string]bool)
		for _, f := range vals {
			removeMap[f] = true
		}

		finalizers := make([]string, 0)
		for _, f := range existing {
			if !removeMap[f] {
				finalizers = append(finalizers, f)
			}
		}

		obj.SetFinalizers(finalizers)
	}
}

// ClearFinalizers removes all finalizers from an object.
func ClearFinalizers() ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetFinalizers(nil)
	}
}

// WithoutResourceVersion removes the resourceVersion from an object.
func WithoutResourceVersion() ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetResourceVersion("")
	}
}

// WithoutUID removes the UID from an object.
// Note: UID is typically read-only, but this sets it to an empty string.
func WithoutUID() ObjectMetaOpt {
	return func(obj metav1.Object) {
		// UID is of type types.UID, but we can't easily set it to empty
		// In practice, this field is managed by Kubernetes and shouldn't be modified
		// This is provided for completeness but may not work as expected
		obj.SetUID("")
	}
}

// WithoutCreationTimestamp removes the creationTimestamp from an object.
func WithoutCreationTimestamp() ObjectMetaOpt {
	return func(obj metav1.Object) {
		obj.SetCreationTimestamp(metav1.Time{})
	}
}

// setMapEntries is a helper function that sets map entries from key-value pairs.
func setMapEntries(m map[string]string, vals ...string) map[string]string {
	if m == nil {
		m = make(map[string]string)
	}

	// if we don't have a value for every key, add an empty
	// string at the end to serve as the value for the last
	// key.
	if len(vals)%2 != 0 {
		vals = append(vals, "")
	}

	for i := 0; i < len(vals); i += 2 {
		key := vals[i]
		val := vals[i+1]

		// If the key already exists in the object, it will be overwritten
		m[key] = val
	}

	return m
}
