package k8s_client

import (
	"context"
	"fmt"
	"strings"

	"go.uber.org/zap"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/util/retry"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/apiutil"
)

// wrapGetError converts the cryptic REST-mapper discovery error that appears
// when VAST CRDs are not installed into a clear, actionable message.
// All other errors are returned unchanged.
func wrapGetError(kind, name, namespace string, err error) error {
	if err == nil {
		return nil
	}
	if strings.Contains(err.Error(), "no matches for") ||
		strings.Contains(err.Error(), "unable to retrieve the complete list of server APIs") {
		return fmt.Errorf("%s %q not found in namespace %q — "+
			"are the VAST CRDs installed? (kubectl get crd | grep vastdata.com)", kind, name, namespace)
	}
	return err
}

type K8sClient struct {
	client client.Client
	logger *zap.Logger
}

// NewK8sClient creates a new K8sClient instance.
func NewK8sClient(client client.Client, logger *zap.Logger) *K8sClient {
	return &K8sClient{
		client: client,
		logger: logger,
	}
}

// WithLogger returns a shallow copy of K8sClient that uses the provided logger.
// Use this to propagate a per-reconcile scoped logger so that all K8sClient
// log lines carry the same reconcile ID as the controller's own log lines.
func (k *K8sClient) WithLogger(l *zap.Logger) *K8sClient {
	return &K8sClient{client: k.client, logger: l}
}

// GetObject is a generic helper that retrieves any Kubernetes object by name and namespace.
// It populates the provided object with data from the API server.
func (k *K8sClient) GetObject(ctx context.Context, name, namespace string, obj client.Object) error {
	key := types.NamespacedName{
		Name:      name,
		Namespace: namespace,
	}
	if err := k.client.Get(ctx, key, obj); err != nil {
		return err
	}
	return nil
}

// UpdateObject updates a Kubernetes object using the client.
func (k *K8sClient) UpdateObject(ctx context.Context, obj client.Object) error {
	if err := k.client.Update(ctx, obj); err != nil {
		return err
	}
	return nil
}

// Client returns the underlying client.Client for use with utilities that require it
// (e.g., controllerutil.CreateOrUpdate).
func (k *K8sClient) Client() client.Client {
	return k.client
}

// refreshObjectMetadata fetches the latest version of obj from the API server
// and copies only its metadata (ResourceVersion, Generation, UID) back into obj,
// leaving all other in-memory changes (spec, status, finalizers…) intact.
// Used by retry helpers to resolve optimistic-concurrency conflicts.
func (k *K8sClient) refreshObjectMetadata(ctx context.Context, obj client.Object) error {
	gvk, err := apiutil.GVKForObject(obj, k.client.Scheme())
	if err != nil {
		return fmt.Errorf("failed to get GVK for object: %w", err)
	}
	objType, err := k.client.Scheme().New(gvk)
	if err != nil {
		return fmt.Errorf("failed to create new object of type %v: %w", gvk, err)
	}
	fresh, ok := objType.(client.Object)
	if !ok {
		return fmt.Errorf("object is not a client.Object")
	}
	key := types.NamespacedName{Name: obj.GetName(), Namespace: obj.GetNamespace()}
	if err := k.client.Get(ctx, key, fresh); err != nil {
		return err
	}
	accessor, err := meta.Accessor(fresh)
	if err != nil {
		return fmt.Errorf("failed to get accessor for object: %w", err)
	}
	obj.SetResourceVersion(accessor.GetResourceVersion())
	obj.SetGeneration(accessor.GetGeneration())
	obj.SetUID(accessor.GetUID())
	return nil
}

// UpdateStatusWithRetry updates the status subresource of obj, retrying on
// conflict by refreshing the object's ResourceVersion from the API server and
// re-applying the caller's desired status values (which remain in obj).
func (k *K8sClient) UpdateStatusWithRetry(ctx context.Context, obj client.Object) error {
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		err := k.client.Status().Update(ctx, obj)
		if apierrors.IsConflict(err) {
			if refreshErr := k.refreshObjectMetadata(ctx, obj); refreshErr != nil {
				return refreshErr
			}
		}
		return err
	})
}

// PatchWithRetry applies mutateFn to obj and persists the change as a merge
// patch, retrying on conflict by re-fetching the full object and re-running
// mutateFn so the patch is always based on the latest server state.
func (k *K8sClient) PatchWithRetry(ctx context.Context, obj client.Object, mutateFn func()) error {
	key := types.NamespacedName{Name: obj.GetName(), Namespace: obj.GetNamespace()}
	return retry.RetryOnConflict(retry.DefaultRetry, func() error {
		if err := k.client.Get(ctx, key, obj); err != nil {
			return err
		}
		base := obj.DeepCopyObject().(client.Object)
		mutateFn()
		return k.client.Patch(ctx, obj, client.MergeFrom(base))
	})
}
