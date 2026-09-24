package k8s_client

import (
	"context"
	"fmt"

	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

// cosiBucketIDIndex is the controller-runtime field index for Bucket.status.bucketID.
const cosiBucketIDIndex = "status.bucketID"

// RegisterCOSIBucketIDIndex indexes Bucket.status.bucketID for O(1) lookup via MatchingFields.
// Call from the cosi namespace only — needs objectstorage.k8s.io CRDs (not present on replication-only installs).
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

// FindCOSIBucketByID returns the Bucket whose status.bucketID matches bucketID.
// Requires RegisterCOSIBucketIDIndex on the manager that owns this client
// (cosi namespace — needs objectstorage.k8s.io CRDs).
func (k *K8sClient) FindCOSIBucketByID(ctx context.Context, bucketID string) (*objectstoragev1alpha1.Bucket, error) {
	list := &objectstoragev1alpha1.BucketList{}
	if err := k.client.List(ctx, list, client.MatchingFields{cosiBucketIDIndex: bucketID}); err != nil {
		return nil, fmt.Errorf("list COSI Buckets by bucketID: %w", err)
	}
	switch len(list.Items) {
	case 0:
		return nil, fmt.Errorf("COSI Bucket with bucketID %q not found", bucketID)
	case 1:
		return &list.Items[0], nil
	default:
		return nil, fmt.Errorf("multiple COSI Buckets with bucketID %q", bucketID)
	}
}
