package k8s_client

import (
	"context"
	"strings"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/handler"
	"sigs.k8s.io/controller-runtime/pkg/reconcile"
)

// ParentNamespace returns labels[nsKey] if set, otherwise fallback.
func ParentNamespace(labels map[string]string, nsKey, fallback string) string {
	if labels != nil {
		if ns := strings.TrimSpace(labels[nsKey]); ns != "" {
			return ns
		}
	}
	return fallback
}

// ParentCRFromObject returns the name and namespace of the VSCR or VVR that
// owns obj. Labels are preferred so the parent can live in a different
// namespace than obj; owner references are the same-namespace fallback.
func ParentCRFromObject(obj client.Object, nameLabel, nsLabel, ownerKind string) (name, ns string) {
	labels := obj.GetLabels()
	ns = obj.GetNamespace()
	if labels != nil {
		name = labels[nameLabel]
		if n := ParentNamespace(labels, nsLabel, ""); n != "" {
			ns = n
		}
	}
	if name == "" {
		if ref := common.OwnerByKind(obj.GetOwnerReferences(), ownerKind); ref != nil {
			return ref.Name, obj.GetNamespace()
		}
	}
	return name, ns
}

// MapToParentCR enqueues the parent VSCR or VVR for obj, including when the
// parent lives in a different namespace.
func MapToParentCR(nameLabel, nsLabel, ownerKind string) handler.MapFunc {
	return func(_ context.Context, obj client.Object) []reconcile.Request {
		name, ns := ParentCRFromObject(obj, nameLabel, nsLabel, ownerKind)
		if name == "" {
			return nil
		}
		return []reconcile.Request{{NamespacedName: types.NamespacedName{Name: name, Namespace: ns}}}
	}
}
