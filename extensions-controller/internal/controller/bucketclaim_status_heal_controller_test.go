package controller

import (
	"context"
	"testing"

	"go.uber.org/zap"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/tools/record"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
)

func healScheme(t *testing.T) *runtime.Scheme {
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

func newFakeHealClient(t *testing.T, objs ...client.Object) client.Client {
	t.Helper()
	s := healScheme(t)
	return fake.NewClientBuilder().
		WithScheme(s).
		WithStatusSubresource(&objectstoragev1alpha1.BucketClaim{}).
		WithIndex(&objectstoragev1alpha1.Bucket{}, k8s_client.COSIBucketClaimUIDIndex, func(obj client.Object) []string {
			ref := obj.(*objectstoragev1alpha1.Bucket).Spec.BucketClaim
			if ref == nil || ref.UID == "" {
				return nil
			}
			return []string{string(ref.UID)}
		}).
		WithObjects(objs...).
		Build()
}

func newHealReconciler(c client.Client) *BucketClaimStatusHealReconciler {
	return &BucketClaimStatusHealReconciler{
		K8s:      k8s_client.NewK8sClient(c, zap.NewNop()),
		Recorder: record.NewFakeRecorder(32),
	}
}

func makeHealClaim(name, ns, uid, bucketName string, ready bool, withFinalizer bool) *objectstoragev1alpha1.BucketClaim {
	claim := &objectstoragev1alpha1.BucketClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: ns,
			UID:       types.UID(uid),
		},
		Spec: objectstoragev1alpha1.BucketClaimSpec{
			BucketClassName: "vastdata-bucket",
			Protocols:       []objectstoragev1alpha1.Protocol{objectstoragev1alpha1.ProtocolS3},
		},
		Status: objectstoragev1alpha1.BucketClaimStatus{
			BucketReady: ready,
			BucketName:  bucketName,
		},
	}
	if withFinalizer {
		controllerutil.AddFinalizer(claim, cosi.BucketClaimProtectionFinalizer)
	}
	return claim
}

func makeBoundBucket(name, claimName, claimNS, claimUID string) *objectstoragev1alpha1.Bucket {
	return &objectstoragev1alpha1.Bucket{
		ObjectMeta: metav1.ObjectMeta{Name: name},
		Spec: objectstoragev1alpha1.BucketSpec{
			DriverName: "csi.vastdata.com",
			BucketClaim: &corev1.ObjectReference{
				Name:      claimName,
				Namespace: claimNS,
				UID:       types.UID(claimUID),
			},
		},
		Status: objectstoragev1alpha1.BucketStatus{BucketReady: true},
	}
}

func reconcileHeal(t *testing.T, r *BucketClaimStatusHealReconciler, claim *objectstoragev1alpha1.BucketClaim) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: client.ObjectKeyFromObject(claim),
	})
	if err != nil {
		t.Fatalf("Reconcile: %v", err)
	}
	return res
}

func getClaim(t *testing.T, c client.Client, ns, name string) *objectstoragev1alpha1.BucketClaim {
	t.Helper()
	claim := &objectstoragev1alpha1.BucketClaim{}
	if err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: name}, claim); err != nil {
		t.Fatalf("get claim: %v", err)
	}
	return claim
}

func TestBucketClaimNeedsStatusHeal(t *testing.T) {
	readyEmpty := makeHealClaim("c", "ns", "u1", "", true, false)
	if !bucketClaimNeedsStatusHeal(readyEmpty) {
		t.Fatal("want true for ready + empty name")
	}
	readyNamedNoFin := makeHealClaim("c", "ns", "u2", "b", true, false)
	if !bucketClaimNeedsStatusHeal(readyNamedNoFin) {
		t.Fatal("want true for ready + name + missing finalizer")
	}
	healthy := makeHealClaim("c", "ns", "u3", "b", true, true)
	if bucketClaimNeedsStatusHeal(healthy) {
		t.Fatal("want false for healthy claim")
	}
	notReady := makeHealClaim("c", "ns", "u4", "", false, false)
	if bucketClaimNeedsStatusHeal(notReady) {
		t.Fatal("want false for not-ready claim")
	}
}

func TestClaimHeal_fillsNameAndFinalizer(t *testing.T) {
	ns := "ns-heal"
	uid := "15d930d6-d765-40ff-b091-7c297db117bd"
	bucketName := "vastdata-bucket" + uid
	claim := makeHealClaim("claim-a", ns, uid, "", true, false)
	bucket := makeBoundBucket(bucketName, claim.Name, ns, uid)

	c := newFakeHealClient(t, claim, bucket)
	r := newHealReconciler(c)

	res := reconcileHeal(t, r, claim)
	if res.RequeueAfter != 0 {
		t.Fatalf("unexpected requeue: %+v", res)
	}

	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != bucketName {
		t.Fatalf("bucketName=%q, want %q", got.Status.BucketName, bucketName)
	}
	if !got.Status.BucketReady {
		t.Fatal("bucketReady cleared; want true")
	}
	if !controllerutil.ContainsFinalizer(got, cosi.BucketClaimProtectionFinalizer) {
		t.Fatal("expected claim protection finalizer")
	}
}

func TestClaimHeal_skipsHealthyClaim(t *testing.T) {
	ns := "ns-heal-healthy"
	uid := "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
	claim := makeHealClaim("claim-ok", ns, uid, "already-named", true, true)
	bucket := makeBoundBucket("other-name", claim.Name, ns, uid)

	c := newFakeHealClient(t, claim, bucket)
	r := newHealReconciler(c)

	_ = reconcileHeal(t, r, claim)
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "already-named" {
		t.Fatalf("overwrote bucketName to %q", got.Status.BucketName)
	}
}

func TestClaimHeal_skipsNotReady(t *testing.T) {
	ns := "ns-heal-notready"
	uid := "11111111-2222-3333-4444-555555555555"
	claim := makeHealClaim("claim-nr", ns, uid, "", false, false)
	bucket := makeBoundBucket("bkt", claim.Name, ns, uid)

	c := newFakeHealClient(t, claim, bucket)
	r := newHealReconciler(c)

	_ = reconcileHeal(t, r, claim)
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "" {
		t.Fatalf("healed not-ready claim: bucketName=%q", got.Status.BucketName)
	}
}

func TestClaimHeal_noopWhenBucketMissing(t *testing.T) {
	ns := "ns-heal-wait"
	uid := "99999999-aaaa-bbbb-cccc-dddddddddddd"
	claim := makeHealClaim("claim-wait", ns, uid, "", true, false)

	c := newFakeHealClient(t, claim)
	r := newHealReconciler(c)

	res := reconcileHeal(t, r, claim)
	if res.RequeueAfter != 0 {
		t.Fatalf("RequeueAfter=%v, want 0 (Bucket watch drives retry)", res.RequeueAfter)
	}
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "" {
		t.Fatalf("invented bucketName=%q", got.Status.BucketName)
	}
}

func TestClaimHeal_healsAfterBucketAppears(t *testing.T) {
	ns := "ns-heal-appear"
	uid := "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
	bucketName := "vastdata-bucket" + uid
	claim := makeHealClaim("claim-appear", ns, uid, "", true, false)

	c := newFakeHealClient(t, claim)
	r := newHealReconciler(c)

	_ = reconcileHeal(t, r, claim)
	if getClaim(t, c, ns, claim.Name).Status.BucketName != "" {
		t.Fatal("expected empty name before Bucket exists")
	}

	bucket := makeBoundBucket(bucketName, claim.Name, ns, uid)
	if err := c.Create(context.Background(), bucket); err != nil {
		t.Fatalf("create bucket: %v", err)
	}

	_ = reconcileHeal(t, r, claim)
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != bucketName {
		t.Fatalf("bucketName=%q, want %q", got.Status.BucketName, bucketName)
	}
	if !controllerutil.ContainsFinalizer(got, cosi.BucketClaimProtectionFinalizer) {
		t.Fatal("expected claim protection finalizer")
	}
}

func TestClaimHeal_restoresFinalizerWhenNameAlreadySet(t *testing.T) {
	ns := "ns-heal-fin"
	uid := "cccccccc-dddd-eeee-ffff-000000000000"
	claim := makeHealClaim("claim-fin", ns, uid, "already-named", true, false)

	c := newFakeHealClient(t, claim)
	r := newHealReconciler(c)

	_ = reconcileHeal(t, r, claim)
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "already-named" {
		t.Fatalf("bucketName changed to %q", got.Status.BucketName)
	}
	if !controllerutil.ContainsFinalizer(got, cosi.BucketClaimProtectionFinalizer) {
		t.Fatal("expected finalizer restored when name already set")
	}
}

func TestClaimHeal_refusesAmbiguousBuckets(t *testing.T) {
	ns := "ns-heal-ambig"
	uid := "abcdef01-2345-6789-abcd-ef0123456789"
	claim := makeHealClaim("claim-ambig", ns, uid, "", true, false)
	b1 := makeBoundBucket("bucket-a"+uid, claim.Name, ns, uid)
	b2 := makeBoundBucket("bucket-b"+uid, claim.Name, ns, uid)

	c := newFakeHealClient(t, claim, b1, b2)
	r := newHealReconciler(c)

	res := reconcileHeal(t, r, claim)
	if res.RequeueAfter != 0 {
		t.Fatalf("unexpected requeue on ambiguous: %+v", res)
	}
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "" {
		t.Fatalf("healed with ambiguous buckets: bucketName=%q", got.Status.BucketName)
	}
}

func TestClaimHeal_ignoresUIDCollisionWrongName(t *testing.T) {
	ns := "ns-heal-uid"
	uid := "deadbeef-dead-beef-dead-beefdeadbeef"
	claim := makeHealClaim("claim-real", ns, uid, "", true, false)
	wrong := makeBoundBucket("bucket-wrong", "other-claim", ns, uid)

	c := newFakeHealClient(t, claim, wrong)
	r := newHealReconciler(c)

	res := reconcileHeal(t, r, claim)
	if res.RequeueAfter != 0 {
		t.Fatalf("RequeueAfter=%v, want 0", res.RequeueAfter)
	}
	got := getClaim(t, c, ns, claim.Name)
	if got.Status.BucketName != "" {
		t.Fatalf("healed from mismatched claim ref: %q", got.Status.BucketName)
	}
}
