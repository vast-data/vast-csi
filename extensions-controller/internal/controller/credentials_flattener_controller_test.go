package controller

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/record"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common/cosi"
)

var (
	cosiTestOnce   sync.Once
	cosiTestCfg    *rest.Config
	cosiTestScheme *runtime.Scheme
	cosiTestErr    error
)

const goodBucketInfo = `{
  "spec": {
    "bucketName": "my-bucket",
    "authenticationType": "KEY",
    "secretS3": {
      "accessKeyID": "AKIAEXAMPLE",
      "accessSecretKey": "secret",
      "endpoint": "http://172.0.0.1:80"
    }
  }
}`

func cosiClientCRDDir() string {
	out, err := exec.Command(
		"go", "list", "-m", "-f", "{{.Dir}}",
		"sigs.k8s.io/container-object-storage-interface/client",
	).Output()
	if err != nil {
		panic("COSI client module dir: " + err.Error())
	}
	return filepath.Join(strings.TrimSpace(string(out)), "config", "crd")
}

func ensureCosiTestEnv() error {
	cosiTestOnce.Do(func() {
		logf.SetLogger(zap.New(zap.WriteTo(os.Stderr), zap.UseDevMode(true)))

		cosiTestScheme = runtime.NewScheme()
		_ = corev1.AddToScheme(cosiTestScheme)
		_ = objectstoragev1alpha1.AddToScheme(cosiTestScheme)

		testEnv := &envtest.Environment{
			CRDDirectoryPaths:     []string{cosiClientCRDDir()},
			ErrorIfCRDPathMissing: true,
			Scheme:                cosiTestScheme,
		}
		if dir := os.Getenv("KUBEBUILDER_ASSETS"); dir != "" {
			testEnv.BinaryAssetsDirectory = dir
		}

		cosiTestCfg, cosiTestErr = testEnv.Start()
	})
	return cosiTestErr
}

func newTestClient(t *testing.T) client.Client {
	t.Helper()
	if err := ensureCosiTestEnv(); err != nil {
		t.Fatalf("envtest: %v", err)
	}
	c, err := client.New(cosiTestCfg, client.Options{Scheme: cosiTestScheme})
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	return c
}

func newReconciler(c client.Client) *CredentialsFlattenerReconciler {
	return &CredentialsFlattenerReconciler{
		Client:   c,
		Scheme:   cosiTestScheme,
		Recorder: record.NewFakeRecorder(32),
	}
}

func makeNS(t *testing.T, c client.Client, name string) {
	t.Helper()
	ns := &corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: name}}
	if err := c.Create(context.Background(), ns); err != nil {
		t.Fatalf("create ns: %v", err)
	}
}

func makeBA(name, ns, credSecret string, annotate bool) *objectstoragev1alpha1.BucketAccess {
	ba := &objectstoragev1alpha1.BucketAccess{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: ns,
		},
		Spec: objectstoragev1alpha1.BucketAccessSpec{
			CredentialsSecretName: credSecret,
		},
	}
	if annotate {
		ba.Annotations = map[string]string{cosi.AnnotationFlatten: "true"}
	}
	return ba
}

func makeCredSecret(name, ns, bucketInfo string) *corev1.Secret {
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
		Data:       map[string][]byte{cosi.BucketInfoKey: []byte(bucketInfo)},
	}
}

func reconcileBA(t *testing.T, r *CredentialsFlattenerReconciler, ba *objectstoragev1alpha1.BucketAccess) ctrl.Result {
	t.Helper()
	res, err := r.Reconcile(context.Background(), ctrl.Request{
		NamespacedName: client.ObjectKeyFromObject(ba),
	})
	if err != nil {
		t.Fatalf("Reconcile: %v", err)
	}
	return res
}

func getSecret(t *testing.T, c client.Client, ns, name string) (*corev1.Secret, error) {
	t.Helper()
	sec := &corev1.Secret{}
	err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: name}, sec)
	return sec, err
}

func getCM(t *testing.T, c client.Client, ns, name string) (*corev1.ConfigMap, error) {
	t.Helper()
	cm := &corev1.ConfigMap{}
	err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: name}, cm)
	return cm, err
}

func TestSetupCredentialsFlattenerController(t *testing.T) {
	if err := ensureCosiTestEnv(); err != nil {
		t.Fatalf("envtest: %v", err)
	}
	mgr, err := ctrl.NewManager(cosiTestCfg, ctrl.Options{
		Scheme:  cosiTestScheme,
		Metrics: metricsserver.Options{BindAddress: "0"},
	})
	if err != nil {
		t.Fatalf("manager: %v", err)
	}
	if err := SetupCredentialsFlattenerController(mgr); err != nil {
		t.Fatalf("Setup: %v", err)
	}
}

func TestReconcile_Create(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-create"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	if err := c.Create(context.Background(), ba); err != nil {
		t.Fatal(err)
	}
	if err := c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo)); err != nil {
		t.Fatal(err)
	}

	reconcileBA(t, r, ba)

	sec, err := getSecret(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatalf("flat secret: %v", err)
	}
	if string(sec.Data["AWS_ACCESS_KEY_ID"]) != "AKIAEXAMPLE" {
		t.Fatalf("access key: %q", sec.Data["AWS_ACCESS_KEY_ID"])
	}
	if string(sec.Data["AWS_SECRET_ACCESS_KEY"]) != "secret" {
		t.Fatalf("secret key: %q", sec.Data["AWS_SECRET_ACCESS_KEY"])
	}
	if !isOwnedBy(sec, ba) {
		t.Fatal("secret missing ownerRef")
	}

	cm, err := getCM(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatalf("flat cm: %v", err)
	}
	if cm.Data["BUCKET_NAME"] != "my-bucket" || cm.Data["BUCKET_HOST"] != "172.0.0.1" ||
		cm.Data["BUCKET_PORT"] != "80" || cm.Data["BUCKET_ENDPOINT"] != "http://172.0.0.1:80" {
		t.Fatalf("cm data: %#v", cm.Data)
	}
	if !isOwnedBy(cm, ba) {
		t.Fatal("cm missing ownerRef")
	}
}

func TestReconcile_WaitForSecret(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-wait"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	if err := c.Create(context.Background(), ba); err != nil {
		t.Fatal(err)
	}

	res := reconcileBA(t, r, ba)
	if res.RequeueAfter == 0 {
		t.Fatal("expected requeue while secret missing")
	}
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("expected no flat yet, got %v", err)
	}

	if err := c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo)); err != nil {
		t.Fatal(err)
	}
	reconcileBA(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); err != nil {
		t.Fatalf("flat after secret appears: %v", err)
	}
}

func TestReconcile_Idempotent(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-idem"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)
	sec1, _ := getSecret(t, c, ns, "creds-flat")
	reconcileBA(t, r, ba)
	sec2, _ := getSecret(t, c, ns, "creds-flat")
	if string(sec1.Data["AWS_ACCESS_KEY_ID"]) != string(sec2.Data["AWS_ACCESS_KEY_ID"]) {
		t.Fatal("data changed on idempotent reconcile")
	}
}

func TestReconcile_MalformedEndpoint(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-malformed-ep"
	makeNS(t, c, ns)

	malformed := strings.Replace(goodBucketInfo, "http://172.0.0.1:80", "://11.0.0.102:80", 1)
	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, malformed))
	reconcileBA(t, r, ba)

	cm, err := getCM(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatalf("flat cm: %v", err)
	}
	if cm.Data["BUCKET_ENDPOINT"] != "http://11.0.0.102:80" {
		t.Fatalf("BUCKET_ENDPOINT: %q", cm.Data["BUCKET_ENDPOINT"])
	}
	if cm.Data["BUCKET_HOST"] != "11.0.0.102" || cm.Data["BUCKET_PORT"] != "80" {
		t.Fatalf("host/port: %#v", cm.Data)
	}
}

func TestReconcile_Rotate(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-rotate"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	src := makeCredSecret("creds", ns, goodBucketInfo)
	_ = c.Create(context.Background(), src)
	reconcileBA(t, r, ba)

	rotated := strings.Replace(goodBucketInfo, "AKIAEXAMPLE", "NEWKEY", 1)
	rotated = strings.Replace(rotated, `"secret"`, `"newsecret"`, 1)
	if err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: "creds"}, src); err != nil {
		t.Fatal(err)
	}
	src.Data[cosi.BucketInfoKey] = []byte(rotated)
	if err := c.Update(context.Background(), src); err != nil {
		t.Fatal(err)
	}
	reconcileBA(t, r, ba)

	sec, _ := getSecret(t, c, ns, "creds-flat")
	if string(sec.Data["AWS_ACCESS_KEY_ID"]) != "NEWKEY" || string(sec.Data["AWS_SECRET_ACCESS_KEY"]) != "newsecret" {
		t.Fatalf("not rotated: %#v", sec.Data)
	}
}

func TestReconcile_AnnotationRemoved(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-ann-off"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)

	if err := c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: "ba"}, ba); err != nil {
		t.Fatal(err)
	}
	ba.Annotations = nil
	if err := c.Update(context.Background(), ba); err != nil {
		t.Fatal(err)
	}
	reconcileBA(t, r, ba)

	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat secret should be deleted: %v", err)
	}
	if _, err := getCM(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat cm should be deleted: %v", err)
	}
	if _, err := getSecret(t, c, ns, "creds"); err != nil {
		t.Fatalf("source secret must remain: %v", err)
	}
}

func TestReconcile_Unannotated(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-unann"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", false)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatal("should not create flat without annotation")
	}
}

func TestReconcile_AnnotationAddedLater(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-ann-later"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", false)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)

	_ = c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: "ba"}, ba)
	ba.Annotations = map[string]string{cosi.AnnotationFlatten: "true"}
	_ = c.Update(context.Background(), ba)
	reconcileBA(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); err != nil {
		t.Fatalf("flat after annotation: %v", err)
	}
}

func TestReconcile_BadJSONNoPrior(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-bad"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, `{}`))
	res := reconcileBA(t, r, ba)
	if res.RequeueAfter == 0 {
		t.Fatal("expected requeue on bad JSON")
	}
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatal("must not create flat from bad JSON")
	}
}

func TestReconcile_BadJSONKeepLastGood(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-keep"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	src := makeCredSecret("creds", ns, goodBucketInfo)
	_ = c.Create(context.Background(), src)
	reconcileBA(t, r, ba)

	_ = c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: "creds"}, src)
	src.Data[cosi.BucketInfoKey] = []byte(`garbage`)
	_ = c.Update(context.Background(), src)
	reconcileBA(t, r, ba)

	sec, err := getSecret(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatal(err)
	}
	if string(sec.Data["AWS_ACCESS_KEY_ID"]) != "AKIAEXAMPLE" {
		t.Fatal("last-good must be preserved")
	}
}

func TestReconcile_RenameCredentialsSecretName(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-rename"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	_ = c.Create(context.Background(), makeCredSecret("creds2", ns, goodBucketInfo))
	reconcileBA(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); err != nil {
		t.Fatal(err)
	}

	_ = c.Get(context.Background(), client.ObjectKey{Namespace: ns, Name: "ba"}, ba)
	ba.Spec.CredentialsSecretName = "creds2"
	_ = c.Update(context.Background(), ba)
	reconcileBA(t, r, ba)

	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatal("old flat should be deleted")
	}
	if _, err := getSecret(t, c, ns, "creds2-flat"); err != nil {
		t.Fatalf("new flat: %v", err)
	}
}

func TestReconcile_ForeignClash(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-clash"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	foreign := &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: "creds-flat", Namespace: ns},
		Data:       map[string][]byte{"keep": []byte("me")},
	}
	_ = c.Create(context.Background(), foreign)

	res := reconcileBA(t, r, ba)
	if res.RequeueAfter == 0 {
		t.Fatal("foreign clash must RequeueAfter so flatten resumes when clash clears")
	}

	sec, _ := getSecret(t, c, ns, "creds-flat")
	if string(sec.Data["keep"]) != "me" {
		t.Fatal("foreign secret must not be overwritten")
	}
	if sec.Data["AWS_ACCESS_KEY_ID"] != nil {
		t.Fatal("must not adopt foreign secret")
	}
}

func TestReconcile_AnnotationValueNotExactTrue(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-true-case"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	ba.Annotations[cosi.AnnotationFlatten] = "True"
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)
	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatal(`"True" must be treated as off`)
	}
}

func TestReconcile_OwnerRefPresent(t *testing.T) {
	c := newTestClient(t)
	r := newReconciler(c)
	ns := "ns-owner"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	_ = c.Create(context.Background(), ba)
	_ = c.Create(context.Background(), makeCredSecret("creds", ns, goodBucketInfo))
	reconcileBA(t, r, ba)

	sec, err := getSecret(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatal(err)
	}
	if len(sec.OwnerReferences) == 0 || sec.OwnerReferences[0].UID != ba.UID {
		t.Fatalf("ownerRef: %+v", sec.OwnerReferences)
	}
	cm, err := getCM(t, c, ns, "creds-flat")
	if err != nil {
		t.Fatal(err)
	}
	if len(cm.OwnerReferences) == 0 || cm.OwnerReferences[0].UID != ba.UID {
		t.Fatalf("cm ownerRef: %+v", cm.OwnerReferences)
	}
}

type failFlatConfigMapClient struct {
	client.Client
}

func (f *failFlatConfigMapClient) Create(ctx context.Context, obj client.Object, opts ...client.CreateOption) error {
	if cm, ok := obj.(*corev1.ConfigMap); ok && strings.HasSuffix(cm.GetName(), "-flat") {
		return errors.New("injected ConfigMap create failure")
	}
	return f.Client.Create(ctx, obj, opts...)
}

func TestEnsureFlatPair_RollbackSecretOnConfigMapFailure(t *testing.T) {
	c := newTestClient(t)
	ns := "ns-rb"
	makeNS(t, c, ns)

	ba := makeBA("ba", ns, "creds", true)
	if err := c.Create(context.Background(), ba); err != nil {
		t.Fatal(err)
	}

	data, err := cosi.ParseBucketInfo([]byte(goodBucketInfo))
	if err != nil {
		t.Fatal(err)
	}

	r := newReconciler(&failFlatConfigMapClient{Client: c})
	if err := r.ensureFlatPair(context.Background(), ba, "creds-flat", data); err == nil {
		t.Fatal("expected ConfigMap create failure")
	}

	if _, err := getSecret(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat secret should be rolled back, got %v", err)
	}
	if _, err := getCM(t, c, ns, "creds-flat"); !apierrors.IsNotFound(err) {
		t.Fatalf("flat cm should not exist, got %v", err)
	}
}
