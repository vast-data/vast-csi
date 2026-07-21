package credsflatten

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	corev1 "k8s.io/api/core/v1"
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

	"github.com/vast-data/vast-csi/extensions-controller/internal/cosi/flatten"
)

var (
	testCfg    *rest.Config
	testScheme *runtime.Scheme
)

func TestMain(m *testing.M) {
	logf.SetLogger(zap.New(zap.WriteTo(os.Stderr), zap.UseDevMode(true)))

	testScheme = runtime.NewScheme()
	_ = corev1.AddToScheme(testScheme)
	_ = objectstoragev1alpha1.AddToScheme(testScheme)

	testEnv := &envtest.Environment{
		CRDDirectoryPaths:     []string{filepath.Join("..", "..", "..", "config", "crd", "bases")},
		ErrorIfCRDPathMissing: true,
		Scheme:                testScheme,
	}
	if dir := os.Getenv("KUBEBUILDER_ASSETS"); dir != "" {
		testEnv.BinaryAssetsDirectory = dir
	}

	var err error
	testCfg, err = testEnv.Start()
	if err != nil {
		panic(err)
	}

	code := m.Run()
	_ = testEnv.Stop()
	os.Exit(code)
}

func newTestClient(t *testing.T) client.Client {
	t.Helper()
	c, err := client.New(testCfg, client.Options{Scheme: testScheme})
	if err != nil {
		t.Fatalf("client: %v", err)
	}
	return c
}

func newReconciler(c client.Client) *BucketAccessReconciler {
	return &BucketAccessReconciler{
		Client:   c,
		Scheme:   testScheme,
		Recorder: record.NewFakeRecorder(32),
	}
}

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
		ba.Annotations = map[string]string{flatten.AnnotationFlatten: "true"}
	}
	return ba
}

func makeCredSecret(name, ns, bucketInfo string) *corev1.Secret {
	return &corev1.Secret{
		ObjectMeta: metav1.ObjectMeta{Name: name, Namespace: ns},
		Data:       map[string][]byte{bucketInfoKey: []byte(bucketInfo)},
	}
}

func reconcileBA(t *testing.T, r *BucketAccessReconciler, ba *objectstoragev1alpha1.BucketAccess) ctrl.Result {
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
