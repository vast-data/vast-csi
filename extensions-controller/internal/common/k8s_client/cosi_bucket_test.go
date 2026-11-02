package k8s_client

import (
	"context"
	"errors"
	"testing"

	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
)

func TestFindCOSIBucketByID(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := objectstoragev1alpha1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}

	wantID := "bkt@1@http://s3:80"
	other := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "other"},
		Status:     objectstoragev1alpha1.BucketStatus{BucketID: "other@1@http://x:80"},
	}
	match := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "match"},
		Status:     objectstoragev1alpha1.BucketStatus{BucketID: wantID},
		Spec: objectstoragev1alpha1.BucketSpec{
			Parameters: map[string]string{
				"vastdata.com/secret-name":      "auth",
				"vastdata.com/secret-namespace": "ns",
			},
		},
	}

	cl := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(other, match).
		WithIndex(&objectstoragev1alpha1.Bucket{}, cosiBucketIDIndex, func(obj client.Object) []string {
			id := obj.(*objectstoragev1alpha1.Bucket).Status.BucketID
			if id == "" {
				return nil
			}
			return []string{id}
		}).
		Build()

	k := NewK8sClient(cl, zap.NewNop())
	got, err := k.FindCOSIBucketByID(context.Background(), wantID)
	if err != nil {
		t.Fatal(err)
	}
	if got.Name != "match" {
		t.Fatalf("got bucket %q, want match", got.Name)
	}

	_, err = k.FindCOSIBucketByID(context.Background(), "missing@1@http://x:80")
	if !errors.Is(err, ErrCOSIBucketNotFound) {
		t.Fatalf("expected ErrCOSIBucketNotFound, got %v", err)
	}
}

func TestFindCOSIBucketForClaim(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := objectstoragev1alpha1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}

	claimUID := types.UID("15d930d6-d765-40ff-b091-7c297db117bd")
	claim := &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{Name: "claim", Namespace: "ns", UID: claimUID},
	}
	match := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "vastdata-bucket" + string(claimUID)},
		Spec: objectstoragev1alpha1.BucketSpec{
			BucketClaim: &corev1.ObjectReference{
				Name: "claim", Namespace: "ns", UID: claimUID,
			},
		},
	}
	other := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "other"},
		Spec: objectstoragev1alpha1.BucketSpec{
			BucketClaim: &corev1.ObjectReference{
				Name: "other-claim", Namespace: "ns", UID: "00000000-0000-0000-0000-000000000000",
			},
		},
	}

	cl := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(other, match).
		WithIndex(&objectstoragev1alpha1.Bucket{}, COSIBucketClaimUIDIndex, func(obj client.Object) []string {
			ref := obj.(*objectstoragev1alpha1.Bucket).Spec.BucketClaim
			if ref == nil || ref.UID == "" {
				return nil
			}
			return []string{string(ref.UID)}
		}).
		Build()

	k := NewK8sClient(cl, zap.NewNop())
	got, err := k.FindCOSIBucketForClaim(context.Background(), claim)
	if err != nil {
		t.Fatal(err)
	}
	if got.Name != match.Name {
		t.Fatalf("got %q, want %q", got.Name, match.Name)
	}

	_, err = k.FindCOSIBucketForClaim(context.Background(), &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{Name: "x", Namespace: "ns", UID: "11111111-1111-1111-1111-111111111111"},
	})
	if !errors.Is(err, ErrCOSIBucketNotFound) {
		t.Fatalf("expected ErrCOSIBucketNotFound, got %v", err)
	}
}
