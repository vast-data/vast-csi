package k8s_client

import (
	"context"
	"errors"
	"fmt"

	"k8s.io/apimachinery/pkg/types"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// cosiBucketIDIndex is the controller-runtime field index for Bucket.status.bucketID.
const cosiBucketIDIndex = "status.bucketID"

// COSIBucketClaimUIDIndex is the field index for Bucket.spec.bucketClaim.uid.
const COSIBucketClaimUIDIndex = "spec.bucketClaim.uid"

var (
	// ErrCOSIBucketNotFound means no Bucket matched the lookup.
	ErrCOSIBucketNotFound = errors.New("cosi bucket not found")
	// ErrCOSIBucketAmbiguous means more than one Bucket matched the lookup.
	ErrCOSIBucketAmbiguous = errors.New("multiple cosi buckets match")
)

// RegisterCOSIIndexes registers all Bucket field indexes needed by the cosi namespace.
// Call only when objectstorage.k8s.io CRDs are present.
func RegisterCOSIIndexes(ctx context.Context, indexer client.FieldIndexer) error {
	if err := RegisterCOSIBucketIDIndex(ctx, indexer); err != nil {
		return err
	}
	return RegisterCOSIBucketClaimUIDIndex(ctx, indexer)
}

// RegisterCOSIBucketIDIndex indexes Bucket.status.bucketID for O(1) lookup via MatchingFields.
func RegisterCOSIBucketIDIndex(ctx context.Context, indexer client.FieldIndexer) error {
	return indexer.IndexField(ctx, &objectstoragev1alpha1.Bucket{}, cosiBucketIDIndex,
		func(obj client.Object) []string {
			id := obj.(*objectstoragev1alpha1.Bucket).Status.BucketID
			if id == "" {
				return nil
			}
			return []string{id}
		},
	)
}

// RegisterCOSIBucketClaimUIDIndex indexes Bucket.spec.bucketClaim.uid for O(1) claim→Bucket lookup.
func RegisterCOSIBucketClaimUIDIndex(ctx context.Context, indexer client.FieldIndexer) error {
	return indexer.IndexField(ctx, &objectstoragev1alpha1.Bucket{}, COSIBucketClaimUIDIndex,
		func(obj client.Object) []string {
			ref := obj.(*objectstoragev1alpha1.Bucket).Spec.BucketClaim
			if ref == nil || ref.UID == "" {
				return nil
			}
			return []string{string(ref.UID)}
		},
	)
}

// uniqueCOSIBucket returns the sole Bucket in items, or a typed not-found/ambiguous error.
func uniqueCOSIBucket(items []objectstoragev1alpha1.Bucket, detail string) (*objectstoragev1alpha1.Bucket, error) {
	switch len(items) {
	case 0:
		return nil, fmt.Errorf("%w: %s", ErrCOSIBucketNotFound, detail)
	case 1:
		return &items[0], nil
	default:
		return nil, fmt.Errorf("%w: %s", ErrCOSIBucketAmbiguous, detail)
	}
}

// FindCOSIBucketByID returns the Bucket whose status.bucketID matches bucketID.
// Requires RegisterCOSIBucketIDIndex (or RegisterCOSIIndexes).
func (k *K8sClient) FindCOSIBucketByID(ctx context.Context, bucketID string) (*objectstoragev1alpha1.Bucket, error) {
	list := &objectstoragev1alpha1.BucketList{}
	if err := k.client.List(ctx, list, client.MatchingFields{cosiBucketIDIndex: bucketID}); err != nil {
		return nil, fmt.Errorf("list COSI Buckets by bucketID: %w", err)
	}
	return uniqueCOSIBucket(list.Items, fmt.Sprintf("bucketID %q", bucketID))
}

// FindCOSIBucketForClaim returns the unique Bucket bound to claim via
// spec.bucketClaim (name, namespace, UID). Requires RegisterCOSIBucketClaimUIDIndex
// (or RegisterCOSIIndexes). Matching ignores Bucket.status.bucketReady.
func (k *K8sClient) FindCOSIBucketForClaim(ctx context.Context, claim *objectstoragev1alpha1.BucketClaim) (*objectstoragev1alpha1.Bucket, error) {
	if claim == nil || claim.UID == "" {
		return nil, fmt.Errorf("claim UID is empty")
	}
	list := &objectstoragev1alpha1.BucketList{}
	if err := k.client.List(ctx, list, client.MatchingFields{COSIBucketClaimUIDIndex: string(claim.UID)}); err != nil {
		return nil, fmt.Errorf("list COSI Buckets by claim UID: %w", err)
	}
	var matches []objectstoragev1alpha1.Bucket
	for i := range list.Items {
		ref := list.Items[i].Spec.BucketClaim
		if ref == nil {
			continue
		}
		if ref.UID == claim.UID &&
			ref.Name == claim.Name &&
			ref.Namespace == claim.Namespace {
			matches = append(matches, list.Items[i])
		}
	}
	return uniqueCOSIBucket(matches, fmt.Sprintf("claim %s/%s uid=%s",
		claim.Namespace, claim.Name, claim.UID))
}

// ClaimKeyFromBucket returns namespaced name for a Bucket's claim ref, or empty if unset.
func ClaimKeyFromBucket(bucket *objectstoragev1alpha1.Bucket) types.NamespacedName {
	if bucket == nil || bucket.Spec.BucketClaim == nil {
		return types.NamespacedName{}
	}
	ref := bucket.Spec.BucketClaim
	return types.NamespacedName{Namespace: ref.Namespace, Name: ref.Name}
}
