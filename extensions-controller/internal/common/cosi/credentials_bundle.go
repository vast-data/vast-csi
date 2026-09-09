package cosi

import (
	"context"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	"sigs.k8s.io/controller-runtime/pkg/client"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

// IsOwnedByBucketAccess reports whether obj has a controller ownerRef to ba.
func IsOwnedByBucketAccess(obj metav1.Object, ba *objectstoragev1alpha1.BucketAccess) bool {
	for _, ref := range obj.GetOwnerReferences() {
		if ref.UID == ba.UID && ref.Controller != nil && *ref.Controller {
			return true
		}
	}
	return false
}

// DeleteOwnedFlatPair deletes Secrets/ConfigMaps labeled for this BA.
// If keepName is non-empty, that name is preserved (rename cleanup).
func DeleteOwnedFlatPair(ctx context.Context, c client.Client, ba *objectstoragev1alpha1.BucketAccess, keepName string) error {
	sel := client.MatchingLabels{LabelBucketAccessUID: string(ba.UID)}

	secList := &corev1.SecretList{}
	if err := c.List(ctx, secList, client.InNamespace(ba.Namespace), sel); err != nil {
		return err
	}
	for i := range secList.Items {
		sec := &secList.Items[i]
		if !IsOwnedByBucketAccess(sec, ba) {
			continue
		}
		if keepName != "" && sec.Name == keepName {
			continue
		}
		if err := c.Delete(ctx, sec); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}

	cmList := &corev1.ConfigMapList{}
	if err := c.List(ctx, cmList, client.InNamespace(ba.Namespace), sel); err != nil {
		return err
	}
	for i := range cmList.Items {
		cm := &cmList.Items[i]
		if !IsOwnedByBucketAccess(cm, ba) {
			continue
		}
		if keepName != "" && cm.Name == keepName {
			continue
		}
		if err := c.Delete(ctx, cm); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}
	return nil
}

// PokeSidecarRegrant forces objectstorage-sidecar to re-Grant: discard the
// credentials bundle (owned *-flat + credentials Secret), then clear BA grant
// status. Credentials Secret and flattener-owned *-flat siblings are one unit.
//
// sec may be nil when the credentials Secret is already gone (prior poke
// deleted it; status clear may still be pending) — owned flats are still wiped
// so consumers cannot keep stale bucket keys.
func PokeSidecarRegrant(ctx context.Context, k *k8s_client.K8sClient, ba *objectstoragev1alpha1.BucketAccess, sec *corev1.Secret) error {
	c := k.Client()
	if err := DeleteOwnedFlatPair(ctx, c, ba, ""); err != nil {
		return err
	}
	if sec != nil {
		// Sidecar owns secret-protection; strip that one finalizer (conflict-retried)
		// then Delete. Do not ClearFinalizers — we do not own Secret lifecycle.
		if err := k.RemoveFinalizer(ctx, sec, SecretProtectionFinalizer); err != nil {
			return err
		}
		if err := c.Delete(ctx, sec); err != nil && !apierrors.IsNotFound(err) {
			return err
		}
	}
	if !ba.Status.AccessGranted && ba.Status.AccountID == "" {
		return nil
	}
	ba.Status.AccessGranted = false
	ba.Status.AccountID = ""
	if err := k.UpdateStatusWithRetry(ctx, ba); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	return nil
}
