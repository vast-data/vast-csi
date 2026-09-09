package controller

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/tools/record"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

func resyncScheme(t *testing.T) *runtime.Scheme {
	t.Helper()
	s := runtime.NewScheme()
	if err := corev1.AddToScheme(s); err != nil {
		t.Fatalf("corev1 scheme: %v", err)
	}
	if err := objectstoragev1alpha1.AddToScheme(s); err != nil {
		t.Fatalf("cosi scheme: %v", err)
	}
	return s
}

func newFakeResyncClient(t *testing.T, objs ...client.Object) client.Client {
	t.Helper()
	s := resyncScheme(t)
	return fake.NewClientBuilder().
		WithScheme(s).
		WithStatusSubresource(
			&objectstoragev1alpha1.BucketAccess{},
			&objectstoragev1alpha1.BucketClaim{},
		).
		WithObjects(objs...).
		Build()
}

func newResyncReconciler(c client.Client) *BucketAccessSecretResyncReconciler {
	return &BucketAccessSecretResyncReconciler{
		K8s:      k8s_client.NewK8sClient(c, zap.NewNop()),
		Recorder: record.NewFakeRecorder(32),
	}
}

func makeClaim(name, ns, bucketName string, ready bool) *objectstoragev1alpha1.BucketClaim {
	return &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
		Spec: objectstoragev1alpha1.BucketClaimSpec{
			BucketClassName: "bc",
			Protocols:       []objectstoragev1alpha1.Protocol{objectstoragev1alpha1.ProtocolS3},
		},
		Status: objectstoragev1alpha1.BucketClaimStatus{
			BucketReady: ready,
			BucketName:  bucketName,
		},
	}
}

func makeGrantedBA(name, ns, claimName, credSecret, accountID string, granted bool) *objectstoragev1alpha1.BucketAccess {
	return &objectstoragev1alpha1.BucketAccess{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
		Spec: objectstoragev1alpha1.BucketAccessSpec{
			BucketClaimName:       claimName,
			BucketAccessClassName: "bac",
			CredentialsSecretName: credSecret,
			Protocol:              objectstoragev1alpha1.ProtocolS3,
		},
		Status: objectstoragev1alpha1.BucketAccessStatus{
			AccessGranted: granted,
			AccountID:     accountID,
		},
	}
}

func bucketInfoWithName(bucketName string) string {
	return strings.Replace(goodBucketInfo, `"bucketName": "my-bucket"`, fmt.Sprintf(`"bucketName": %q`, bucketName), 1)
}

func reconcileResync(t *testing.T, r *BucketAccessSecretResyncReconciler, ba *objectstoragev1alpha1.BucketAccess) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: client.ObjectKeyFromObject(ba),
	})
	if err != nil {
		t.Fatalf("Reconcile: %v", err)
	}
	return res
}

func getBA(t *testing.T, c client.Client, ns, name string) *objectstoragev1alpha1.BucketAccess {
	t.Helper()
	ba := &objectstoragev1alpha1.BucketAccess{}
	if err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: name}, ba); err != nil {
		t.Fatalf("get BA: %v", err)
	}
	return ba
}

func TestResync_mismatch_deletesSecretAndClearsStatus(t *testing.T) {
	ns := "ns-resync-mismatch"
	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	sec := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	res := reconcileResync(t, r, ba)
	if res.RequeueAfter != 0 {
		t.Fatalf("expected no requeue after poke, got %#v", res)
	}

	_, err := getSecret(t, c, ns, "creds")
	if !apierrors.IsNotFound(err) {
		t.Fatalf("secret should be deleted, err=%v", err)
	}
	got := getBA(t, c, ns, "ba")
	if got.Status.AccessGranted {
		t.Fatal("AccessGranted should be false")
	}
	if got.Status.AccountID != "" {
		t.Fatalf("AccountID should be empty, got %q", got.Status.AccountID)
	}
}

func TestResync_mismatch_clearsFinalizerThenDeletes(t *testing.T) {
	ns := "ns-resync-finalizer"
	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	sec := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))
	sec.Finalizers = []string{cosi.SecretProtectionFinalizer}

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	_ = reconcileResync(t, r, ba)
	_, err := getSecret(t, c, ns, "creds")
	if !apierrors.IsNotFound(err) {
		t.Fatalf("secret should be gone after finalizer clear + delete, err=%v", err)
	}
	got := getBA(t, c, ns, "ba")
	if got.Status.AccessGranted || got.Status.AccountID != "" {
		t.Fatalf("status should be cleared: %+v", got.Status)
	}
}

func TestResync_secretMissingWhileGranted_clearsStatusAndFlat(t *testing.T) {
	ns := "ns-resync-half-poke"
	scheme := resyncScheme(t)
	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	ba.UID = "ba-uid-half-poke"
	ba.Annotations = map[string]string{cosi.AnnotationFlatten: "true"}
	creds := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithStatusSubresource(
			&objectstoragev1alpha1.BucketAccess{},
			&objectstoragev1alpha1.BucketClaim{},
		).
		WithObjects(claim, ba, creds).
		Build()
	flat := &CredentialsFlattenerReconciler{
		Client:   c,
		Scheme:   scheme,
		Recorder: record.NewFakeRecorder(32),
	}
	reconcileBA(t, flat, ba)
	if err := c.Delete(context.Background(), creds); err != nil {
		t.Fatalf("delete creds to simulate half-poke: %v", err)
	}

	_ = reconcileResync(t, newResyncReconciler(c), ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("stale flat secret should be deleted, err=%v", err)
	}
	if _, err := getCM(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("stale flat cm should be deleted, err=%v", err)
	}
	got := getBA(t, c, ns, "ba")
	if got.Status.AccessGranted || got.Status.AccountID != "" {
		t.Fatalf("status should be cleared: %+v", got.Status)
	}
}

func TestResync_match_noop(t *testing.T) {
	ns := "ns-resync-match"
	claim := makeClaim("claim", ns, "my-bucket", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOK", true)
	sec := makeCredSecret("creds", ns, goodBucketInfo)

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	res := reconcileResync(t, r, ba)
	if res.RequeueAfter != 0 {
		t.Fatalf("expected no requeue on match, got %#v", res)
	}
	if _, err := getSecret(t, c, ns, "creds"); err != nil {
		t.Fatalf("secret should remain: %v", err)
	}
	got := getBA(t, c, ns, "ba")
	if !got.Status.AccessGranted || got.Status.AccountID != "AKIAOK" {
		t.Fatalf("status should be unchanged: %+v", got.Status)
	}
}

func TestResync_claimNotReady_noop(t *testing.T) {
	ns := "ns-resync-claim-not-ready"
	claim := makeClaim("claim", ns, "bucket-new", false)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	sec := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	_ = reconcileResync(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds"); err != nil {
		t.Fatalf("secret should remain: %v", err)
	}
	got := getBA(t, c, ns, "ba")
	if !got.Status.AccessGranted {
		t.Fatal("should not clear status when claim not ready")
	}
}

func TestResync_notGranted_noop(t *testing.T) {
	ns := "ns-resync-not-granted"
	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "", false)
	sec := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	_ = reconcileResync(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds"); err != nil {
		t.Fatalf("secret should remain: %v", err)
	}
}

func TestResync_unparseableBucketInfo_noop(t *testing.T) {
	ns := "ns-resync-bad-json"
	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	sec := makeCredSecret("creds", ns, `garbage`)

	c := newFakeResyncClient(t, claim, ba, sec)
	r := newResyncReconciler(c)

	_ = reconcileResync(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds"); err != nil {
		t.Fatalf("secret should remain: %v", err)
	}
	got := getBA(t, c, ns, "ba")
	if !got.Status.AccessGranted || got.Status.AccountID != "AKIAOLD" {
		t.Fatalf("status should be unchanged on bad JSON: %+v", got.Status)
	}
}

// Resync invalidates credentials + owned *-flat as one bundle. After sidecar
// recreate, flattener builds a fresh *-flat for the new bucket.
func TestResync_thenFlattener_deletesFlatThenRebuilds(t *testing.T) {
	ns := "ns-resync-then-flat"
	ctx := context.Background()
	scheme := resyncScheme(t)

	claim := makeClaim("claim", ns, "bucket-new", true)
	ba := makeGrantedBA("ba", ns, "claim", "creds", "AKIAOLD", true)
	ba.UID = "ba-uid-resync-flat"
	ba.Annotations = map[string]string{cosi.AnnotationFlatten: "true"}
	creds := makeCredSecret("creds", ns, bucketInfoWithName("bucket-old"))

	c := fake.NewClientBuilder().
		WithScheme(scheme).
		WithStatusSubresource(
			&objectstoragev1alpha1.BucketAccess{},
			&objectstoragev1alpha1.BucketClaim{},
		).
		WithObjects(claim, ba, creds).
		Build()
	resync := newResyncReconciler(c)
	flat := &CredentialsFlattenerReconciler{
		Client:   c,
		Scheme:   scheme,
		Recorder: record.NewFakeRecorder(32),
	}

	reconcileBA(t, flat, ba)
	if _, err := getCM(t, c, ns, "creds-flat"); err != nil {
		t.Fatalf("initial flat cm: %v", err)
	}
	if _, err := getSecret(t, c, ns, "creds-flat"); err != nil {
		t.Fatalf("initial flat secret: %v", err)
	}

	_ = reconcileResync(t, resync, ba)
	if _, err := getSecret(t, c, ns, "creds"); !apierrors.IsNotFound(err) {
		t.Fatalf("creds should be deleted after resync, err=%v", err)
	}
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat secret should be deleted with credentials bundle, err=%v", err)
	}
	if _, err := getCM(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat cm should be deleted with credentials bundle, err=%v", err)
	}
	gotBA := getBA(t, c, ns, "ba")
	if gotBA.Status.AccessGranted || gotBA.Status.AccountID != "" {
		t.Fatalf("grant should be cleared: %+v", gotBA.Status)
	}

	res := reconcileBA(t, flat, ba)
	if res.RequeueAfter == 0 {
		t.Fatal("flattener should requeue while creds Secret missing")
	}

	if err := c.Create(ctx, makeCredSecret("creds", ns, bucketInfoWithName("bucket-new"))); err != nil {
		t.Fatalf("recreate creds: %v", err)
	}
	reconcileBA(t, flat, ba)

	cm, err := getCM(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatalf("flat cm after recreate: %v", err)
	}
	if cm.Data["BUCKET_NAME"] != "bucket-new" {
		t.Fatalf("after recreate flat should rebuild for new bucket, got %q", cm.Data["BUCKET_NAME"])
	}
}
