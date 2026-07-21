package credsflatten

import (
	"testing"

	ctrl "sigs.k8s.io/controller-runtime"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"
)

func TestSetupBucketAccessReconciler(t *testing.T) {
	mgr, err := ctrl.NewManager(testCfg, ctrl.Options{
		Scheme:  testScheme,
		Metrics: metricsserver.Options{BindAddress: "0"},
	})
	if err != nil {
		t.Fatalf("manager: %v", err)
	}
	if err := SetupBucketAccessReconciler(mgr); err != nil {
		t.Fatalf("Setup: %v", err)
	}
}
