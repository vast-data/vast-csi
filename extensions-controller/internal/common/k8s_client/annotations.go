package k8s_client

import (
	"context"
	"fmt"

	"sigs.k8s.io/controller-runtime/pkg/client"
)

func (k *K8sClient) HasAnnotation(obj client.Object, key string) bool {
	_, ok := obj.GetAnnotations()[key]
	return ok
}

func (k *K8sClient) GetAnnotation(obj client.Object, key string) (value string, found bool) {
	annotations := obj.GetAnnotations()
	if annotations == nil {
		return "", false
	}
	value, found = annotations[key]
	return value, found
}

func (k *K8sClient) RemoveAnnotation(obj client.Object, key string) {
	annotations := obj.GetAnnotations()

	if annotations == nil {
		return
	}

	delete(annotations, key)

	obj.SetAnnotations(annotations)
}

// SetAnnotation mutates obj in memory only.
func (k *K8sClient) SetAnnotation(obj client.Object, key, value string) {
	ann := obj.GetAnnotations()

	if ann == nil {
		ann = make(map[string]string, 1)
	}

	ann[key] = value

	obj.SetAnnotations(ann)
}

// SetAnnotationAndUpdate sets the annotation in memory and persists it to the
// API server using a merge patch, retrying on conflict.
func (k *K8sClient) SetAnnotationAndUpdate(ctx context.Context, obj client.Object, key, value string) error {
	if err := k.PatchWithRetry(ctx, obj, func() { k.SetAnnotation(obj, key, value) }); err != nil {
		return fmt.Errorf("failed to patch annotation %q on %s/%s: %w",
			key, obj.GetNamespace(), obj.GetName(), err)
	}
	return nil
}
