package webhook

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"go.uber.org/zap"
	admissionv1 "k8s.io/api/admission/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
)

func newBucketParamsInjector(client client.Client) *BucketParamsInjector {
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)
	decoder := admission.NewDecoder(scheme)
	return &BucketParamsInjector{
		Client:     client,
		Decoder:    decoder,
		Rainbow:    logging.New(zap.NewNop(), false),
		DriverName: cosi.VastCOSIDriverName,
	}
}

func bucketAdmissionRequest(bucket *objectstoragev1alpha1.Bucket) admission.Request {
	raw, err := json.Marshal(bucket)
	if err != nil {
		panic(err)
	}
	return admission.Request{
		AdmissionRequest: admissionv1.AdmissionRequest{
			Namespace: bucket.Namespace,
			Object: runtime.RawExtension{Raw: raw},
		},
	}
}

func TestBucketParamsInjector_claimNotFound(t *testing.T) {
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)
	client := fake.NewClientBuilder().WithScheme(scheme).Build()

	bucket := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "bc-uid", Namespace: "default"},
		Spec: objectstoragev1alpha1.BucketSpec{
			DriverName: cosi.VastCOSIDriverName,
			BucketClaim: &corev1.ObjectReference{
				Name:      "missing-claim",
				Namespace: "default",
			},
			Parameters: map[string]string{"root_export": "/cosi"},
		},
	}

	resp := newBucketParamsInjector(client).Handle(context.Background(), bucketAdmissionRequest(bucket))
	if resp.Allowed {
		t.Fatalf("expected deny when BucketClaim missing, got allowed: %s", resp.AdmissionResponse.Result.Message)
	}
}

func TestBucketParamsInjector_mergeClaimAnnotations(t *testing.T) {
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)

	claim := &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "clone-claim",
			Namespace: "default",
			Annotations: map[string]string{
				"cosi.vastdata.com/sourceBucket": "prod-data",
			},
		},
	}
	client := fake.NewClientBuilder().WithScheme(scheme).WithObjects(claim).Build()

	bucket := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "bc-uid", Namespace: "default"},
		Spec: objectstoragev1alpha1.BucketSpec{
			DriverName: cosi.VastCOSIDriverName,
			BucketClaim: &corev1.ObjectReference{
				Name:      "clone-claim",
				Namespace: "default",
			},
			Parameters: map[string]string{"root_export": "/cosi", "view_policy": "default"},
		},
	}

	resp := newBucketParamsInjector(client).Handle(context.Background(), bucketAdmissionRequest(bucket))
	if !resp.Allowed {
		t.Fatalf("expected allowed patch, got: %s", resp.AdmissionResponse.Result.Message)
	}
	if len(resp.Patches) == 0 {
		t.Fatal("expected JSON patch")
	}

	mergedJSON, err := json.Marshal(resp.Patches)
	if err != nil {
		t.Fatalf("marshal patches: %v", err)
	}
	// Full annotation keys preserved (JSON Pointer escapes '/' as ~1).
	if !containsAll(string(mergedJSON), "cosi.vastdata.com~1sourceBucket", "prod-data") {
		t.Fatalf("patch missing clone params: %s", string(mergedJSON))
	}
}

func TestBucketParamsInjector_incompleteCloneStillMerged(t *testing.T) {
	// Mutation webhook does not validate; CreateBucket validates later.
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)

	claim := &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "bad-clone",
			Namespace: "default",
			Annotations: map[string]string{
				"cosi.vastdata.com/blockingClones": "true",
			},
		},
	}
	client := fake.NewClientBuilder().WithScheme(scheme).WithObjects(claim).Build()

	bucket := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "bc-uid", Namespace: "default"},
		Spec: objectstoragev1alpha1.BucketSpec{
			DriverName: cosi.VastCOSIDriverName,
			BucketClaim: &corev1.ObjectReference{
				Name:      "bad-clone",
				Namespace: "default",
			},
			Parameters: map[string]string{"root_export": "/cosi"},
		},
	}

	resp := newBucketParamsInjector(client).Handle(context.Background(), bucketAdmissionRequest(bucket))
	if !resp.Allowed {
		t.Fatalf("mutation webhook must allow incomplete clone params, got: %s", resp.AdmissionResponse.Result.Message)
	}
	if len(resp.Patches) == 0 {
		t.Fatal("expected JSON patch merging blockingClones")
	}
}

func TestBucketParamsInjector_noDriverNameSkipped(t *testing.T) {
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)
	client := fake.NewClientBuilder().WithScheme(scheme).Build()

	bucket := &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: "bc-uid", Namespace: "default"},
		Spec: objectstoragev1alpha1.BucketSpec{
			BucketClassName: "some-class",
			Parameters:      map[string]string{"root_export": "/cosi"},
		},
	}

	resp := newBucketParamsInjector(client).Handle(context.Background(), bucketAdmissionRequest(bucket))
	if !resp.Allowed {
		t.Fatalf("expected allow when DriverName empty, got: %s", resp.AdmissionResponse.Result.Message)
	}
	if len(resp.Patches) != 0 {
		t.Fatal("expected no patch when DriverName empty")
	}
}

func TestBucketParamsInjector_decodeError(t *testing.T) {
	scheme := runtime.NewScheme()
	objectstoragev1alpha1.AddToScheme(scheme)
	client := fake.NewClientBuilder().WithScheme(scheme).Build()

	resp := newBucketParamsInjector(client).Handle(context.Background(), admission.Request{
		AdmissionRequest: admissionv1.AdmissionRequest{
			Namespace: "default",
			Object:    runtime.RawExtension{Raw: []byte(`{not-json`)},
		},
	})
	if resp.Allowed {
		t.Fatal("expected Errored on decode failure, got Allowed")
	}
}

func containsAll(s string, parts ...string) bool {
	for _, p := range parts {
		if !strings.Contains(s, p) {
			return false
		}
	}
	return true
}
