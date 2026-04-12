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

package k8s_client

import (
	"context"

	"go.uber.org/zap"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/client-go/util/retry"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
)

// HasFinalizer checks if an object has the specified finalizer.
// Uses controllerutil.ContainsFinalizer for consistency with standard Kubernetes patterns.
func (k *K8sClient) HasFinalizer(obj client.Object, finalizer string) bool {
	return controllerutil.ContainsFinalizer(obj, finalizer)
}

// AddFinalizer adds a finalizer to a resource if it doesn't already exist and updates it.
// Uses controllerutil.AddFinalizer for consistency with standard Kubernetes patterns.
func (k *K8sClient) AddFinalizer(ctx context.Context, obj client.Object, finalizer string) error {
	if controllerutil.AddFinalizer(obj, finalizer) {
		k.logger.Info("adding finalizer to resource",
			zap.String("kind", obj.GetObjectKind().GroupVersionKind().Kind),
			zap.String("name", obj.GetName()),
			zap.String("namespace", obj.GetNamespace()),
			zap.String("finalizer", finalizer))
		return k.updateFinalizerWithRetry(ctx, obj)
	}
	return nil
}

// EnsureFinalizer ensures that a finalizer exists on the object.
// Returns (true, nil) when the finalizer was freshly added, (false, nil) when
// it was already present, and (false, err) on any API error.
func (k *K8sClient) EnsureFinalizer(ctx context.Context, obj client.Object, finalizer string) (bool, error) {
	if controllerutil.AddFinalizer(obj, finalizer) {
		k.logger.Info("adding finalizer to resource",
			zap.String("kind", obj.GetObjectKind().GroupVersionKind().Kind),
			zap.String("name", obj.GetName()),
			zap.String("namespace", obj.GetNamespace()),
			zap.String("finalizer", finalizer))
		return true, k.updateFinalizerWithRetry(ctx, obj)
	}
	return false, nil
}

// RemoveFinalizer removes a finalizer from a resource if it exists and updates it.
// Uses controllerutil.RemoveFinalizer for consistency with standard Kubernetes patterns.
func (k *K8sClient) RemoveFinalizer(ctx context.Context, obj client.Object, finalizer string) error {
	if controllerutil.RemoveFinalizer(obj, finalizer) {
		k.logger.Info("removing finalizer from resource",
			zap.String("kind", obj.GetObjectKind().GroupVersionKind().Kind),
			zap.String("name", obj.GetName()),
			zap.String("namespace", obj.GetNamespace()),
			zap.String("finalizer", finalizer))
		return k.updateFinalizerWithRetry(ctx, obj)
	}
	return nil
}

// ClearFinalizers removes ALL finalizers from an object in a single API call.
// Use this only for objects whose full lifecycle is owned by this controller so
// that clearing foreign finalizers (e.g. csi-addons' vgr-protection) is safe.
func (k *K8sClient) ClearFinalizers(ctx context.Context, obj client.Object) error {
	if len(obj.GetFinalizers()) == 0 {
		return nil
	}
	k.logger.Info("clearing all finalizers from resource",
		zap.String("kind", obj.GetObjectKind().GroupVersionKind().Kind),
		zap.String("name", obj.GetName()),
		zap.String("namespace", obj.GetNamespace()),
		zap.Strings("finalizers", obj.GetFinalizers()))
	obj.SetFinalizers(nil)
	return k.updateFinalizerWithRetry(ctx, obj)
}

func (k *K8sClient) updateFinalizerWithRetry(ctx context.Context, obj client.Object) error {
	err := retry.RetryOnConflict(retry.DefaultRetry, func() error {
		return k.finalizerRetryOnConflictFunc(ctx, obj)
	})
	if err != nil {
		k.logger.Error("failed to update finalizer on resource",
			zap.Error(err),
			zap.String("kind", obj.GetObjectKind().GroupVersionKind().Kind),
			zap.String("name", obj.GetName()),
			zap.String("namespace", obj.GetNamespace()))
	}
	return err
}

func (k *K8sClient) finalizerRetryOnConflictFunc(ctx context.Context, obj client.Object) error {
	err := k.UpdateObject(ctx, obj)
	if apierrors.IsConflict(err) {
		uErr := k.refreshObjectMetadata(ctx, obj)
		if uErr != nil {
			return uErr
		}
		k.logger.Info("retrying finalizer update after conflict")
	}
	return err
}
