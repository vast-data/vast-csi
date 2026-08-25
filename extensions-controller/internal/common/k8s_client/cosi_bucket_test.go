package k8s_client

import (
	"context"
	"testing"

	"go.uber.org/zap"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
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
	if err == nil {
		t.Fatal("expected not found")
	}
}
