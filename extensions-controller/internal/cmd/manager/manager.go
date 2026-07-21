/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package manager

import (
	"crypto/tls"
	"os"
	"sync"

	"github.com/spf13/cobra"
	k8sclient "github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	zapLgr "go.uber.org/zap"
	"go.uber.org/zap/zapcore"
	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	replicationv1alpha1 "github.com/csi-addons/kubernetes-csi-addons/api/replication.storage/v1alpha1"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	objectstoragev1alpha1 "sigs.k8s.io/container-object-storage-interface/client/apis/objectstorage/v1alpha1"
)

// ---------------------------------------------------------------------------
// Manager interface
// ---------------------------------------------------------------------------

// Manager is the service-locator interface passed to every subcommand.
// Both SharedManager (operator) and CLIManager (CLI) implement it so that
// subcommands can obtain a logger and a Kubernetes client without knowing
// which mode they are running in.
type Manager interface {
	GetLogger() *zapLgr.Logger
	GetK8sClient() (*k8sclient.K8sClient, error)
}

// ---------------------------------------------------------------------------
// SharedManager — used by operator subcommands
// ---------------------------------------------------------------------------

// SharedManager holds the singleton controller-runtime manager shared across
// all operator controllers.
type SharedManager struct {
	mgr        ctrl.Manager
	mgrErr     error
	mgrOnce    sync.Once
	logger     *zapLgr.Logger
	loggerOnce sync.Once
	k8s        *k8sclient.K8sClient
	k8sOnce    sync.Once
	rootCmd    *cobra.Command
	cfg        *config.Config
}

// RegisterCLIFlags registers flags that are common to all CLI subcommands.
// Note: --kubeconfig and --kubecontext are bound by the factory via CLIManager.
func RegisterCLIFlags(c *cobra.Command) {
	c.PersistentFlags().Bool("no-color", false, "Disable colored output")
}

// RegisterFlags registers manager-specific flags with the cobra command.
func RegisterFlags(c *cobra.Command, cfg *config.Config) {
	c.PersistentFlags().BoolVar(&cfg.SSLVerify, "ssl-verify", false,
		"If set, TLS certificates will be verified when connecting to the VAST cluster API.")
	c.PersistentFlags().StringVar(&cfg.HealthProbeBindAddress, "health-probe-bind-address", ":8081",
		"The address the health probe endpoint binds to.")
	c.PersistentFlags().StringVar(&cfg.MetricsBindAddress, "metrics-bind-address", "0",
		"The address the metrics endpoint binds to. Use :8080 for HTTP, or 0 to disable.")
	c.PersistentFlags().BoolVar(&cfg.EnableHTTP2, "enable-http2", false,
		"If set, HTTP/2 will be enabled for the servers.")
	c.PersistentFlags().BoolVar(&cfg.DevLogging, "dev-logging", false,
		"If set, use human-readable console logging (timestamps, caller, coloured levels) instead of JSON production logs.")
	c.PersistentFlags().IntVar(&cfg.MaxConcurrentReconciles, "max-concurrent-reconciles", 5,
		"Maximum parallel reconcile workers per controller.")
}

// NewSharedManager creates a new SharedManager instance.
// cfg must be the same Config pointer that RegisterFlags bound its flags to;
// it is read lazily (in GetLogger) after cobra has parsed the command line.
func NewSharedManager(rootCmd *cobra.Command, cfg *config.Config) *SharedManager {
	return &SharedManager{rootCmd: rootCmd, cfg: cfg}
}

// Get returns the controller-runtime manager, creating it on the first call.
func (sm *SharedManager) Get(customOpts ...func(*ctrl.Options)) (ctrl.Manager, error) {
	sm.mgrOnce.Do(func() {
		probeAddr, _ := sm.rootCmd.Flags().GetString("health-probe-bind-address")
		metricsAddr, _ := sm.rootCmd.Flags().GetString("metrics-bind-address")
		enableHTTP2, _ := sm.rootCmd.Flags().GetBool("enable-http2")

		var tlsOpts []func(*tls.Config)
		if !enableHTTP2 {
			tlsOpts = append(tlsOpts, func(c *tls.Config) {
				c.NextProtos = []string{"http/1.1"}
			})
		}

		scheme := runtime.NewScheme()
		utilruntime.Must(clientgoscheme.AddToScheme(scheme))
		utilruntime.Must(replicationv1alpha1.AddToScheme(scheme))
		utilruntime.Must(vastv1alpha1.AddToScheme(scheme))
		utilruntime.Must(objectstoragev1alpha1.AddToScheme(scheme))

		opts := ctrl.Options{
			Scheme: scheme,
			Metrics: metricsserver.Options{
				BindAddress: metricsAddr,
				TLSOpts:     tlsOpts,
			},
			HealthProbeBindAddress: probeAddr,
		}
		for _, customOpt := range customOpts {
			customOpt(&opts)
		}

		sm.mgr, sm.mgrErr = ctrl.NewManager(ctrl.GetConfigOrDie(), opts)
		if sm.mgrErr != nil {
			return
		}

		setupLog := ctrl.Log.WithName("setup")
		if err := sm.mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
			setupLog.Error(err, "unable to set up health check")
			os.Exit(1)
		}
		if err := sm.mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
			setupLog.Error(err, "unable to set up ready check")
			os.Exit(1)
		}
	})
	return sm.mgr, sm.mgrErr
}

// GetLogger returns the shared zap logger, creating it on the first call.
// When cfg.DevLogging is true a human-readable console logger is built;
// otherwise the standard JSON production logger is used.
func (sm *SharedManager) GetLogger() *zapLgr.Logger {
	sm.loggerOnce.Do(func() {
		if sm.cfg != nil && sm.cfg.DevLogging {
			sm.logger = newDevLogger()
		} else {
			var err error
			sm.logger, err = zapLgr.NewProduction()
			if err != nil {
				panic(err)
			}
		}
	})
	return sm.logger
}

// newDevLogger builds a human-readable console logger suitable for development
// and debugging.  Output goes to stdout only (no file sink).
// Format: <timestamp>  <level>  <caller>  <message>  {fields...}
func newDevLogger() *zapLgr.Logger {
	encCfg := zapLgr.NewDevelopmentEncoderConfig()
	encCfg.TimeKey = "T"
	encCfg.EncodeTime = zapcore.ISO8601TimeEncoder
	encCfg.EncodeLevel = zapcore.CapitalColorLevelEncoder
	encoder := zapcore.NewConsoleEncoder(encCfg)
	core := zapcore.NewCore(encoder, zapcore.Lock(os.Stdout), zapcore.InfoLevel)
	return zapLgr.New(core, zapLgr.AddCaller(), zapLgr.AddStacktrace(zapcore.ErrorLevel))
}

// GetK8sClient returns a K8sClient wrapping the controller-runtime manager's
// client.  Implements the Manager interface; only meaningful after Get() has
// been called (i.e. inside a controller subcommand).
func (sm *SharedManager) GetK8sClient() (*k8sclient.K8sClient, error) {
	sm.k8sOnce.Do(func() {
		mgr, err := sm.Get()
		if err != nil {
			return
		}
		sm.k8s = k8sclient.NewK8sClient(mgr.GetClient(), sm.GetLogger())
	})
	return sm.k8s, sm.mgrErr
}

// Start starts the controller-runtime manager.  Call once after all
// controllers are registered.
func (sm *SharedManager) Start() error {
	if sm.mgr == nil {
		if _, err := sm.Get(); err != nil {
			return err
		}
	}
	logger := sm.GetLogger()
	defer logger.Sync() //nolint:errcheck
	return sm.mgr.Start(ctrl.SetupSignalHandler())
}

// ---------------------------------------------------------------------------
// CLIManager — used by user-facing CLI subcommands
// ---------------------------------------------------------------------------

// CLIManager implements Manager for interactive CLI usage.
// It holds a Factory whose flags (--kubeconfig, --kubecontext) are bound to
// the root cobra command at construction time, so cobra populates them before
// any subcommand runs.
type CLIManager struct {
	factory    k8sclient.Factory
	logger     *zapLgr.Logger
	loggerOnce sync.Once
	k8s        *k8sclient.K8sClient
	k8sErr     error
	k8sOnce    sync.Once
}

// NewCLIManager creates a CLIManager and immediately binds --kubeconfig and
// --kubecontext flags onto the root command's persistent flag set, exactly as
// the velero factory does via factory.BindFlags.
func NewCLIManager(rootCmd *cobra.Command) *CLIManager {
	f := k8sclient.NewFactory("vastrep")
	f.BindFlags(rootCmd.PersistentFlags())
	return &CLIManager{factory: f}
}

// GetLogger returns a development zap logger suitable for human-readable CLI output.
func (m *CLIManager) GetLogger() *zapLgr.Logger {
	m.loggerOnce.Do(func() {
		var err error
		m.logger, err = zapLgr.NewDevelopment()
		if err != nil {
			panic(err)
		}
	})
	return m.logger
}

// GetK8sClient returns a K8sClient built from the factory.
// Because the factory's fields were bound to cobra flags, kubeconfig and
// kubecontext are already populated by the time RunE is called.
func (m *CLIManager) GetK8sClient() (*k8sclient.K8sClient, error) {
	m.k8sOnce.Do(func() {
		m.k8s, m.k8sErr = m.factory.K8sClientForLocal(m.GetLogger())
	})
	return m.k8s, m.k8sErr
}
