package webhook

import (
	"crypto/tls"
	"fmt"
	"os"
	"path/filepath"
	"regexp"

	"github.com/spf13/cobra"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/certwatcher"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	ctrlwebhook "sigs.k8s.io/controller-runtime/pkg/webhook"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	pvcwebhook "github.com/vast-data/vast-csi/extensions-controller/internal/webhook"
)

var setupLog = ctrl.Log.WithName("setup")

// RegisterFlags registers webhook-specific flags with the cobra command.
func RegisterFlags(c *cobra.Command, cfg *config.Config) {
	// Feature flag
	c.PersistentFlags().BoolVar(&cfg.PvcLabelWebhookEnabled, "enable-pvc-label-webhook", false,
		"Enable the PVC label injection webhook")
	c.PersistentFlags().BoolVar(&cfg.VSCRValidationWebhookEnabled, "enable-vscr-validation-webhook", false,
		"Enable the VastStorageClassReplication admission webhook")
	c.PersistentFlags().BoolVar(&cfg.VVRValidationWebhookEnabled, "enable-vvr-validation-webhook", false,
		"Enable the VastVolumeReplication admission webhook")

	// Webhook flags
	c.PersistentFlags().StringVar(&cfg.WebhookCertPath, "webhook-cert-path", "/tmp/k8s-webhook-server/serving-certs",
		"The directory that contains the webhook TLS certificate and key files.")
	c.PersistentFlags().StringVar(&cfg.WebhookCertName, "webhook-cert-name", "tls.crt",
		"The name of the webhook certificate file.")
	c.PersistentFlags().StringVar(&cfg.WebhookCertKey, "webhook-cert-key", "tls.key",
		"The name of the webhook key file.")
	c.PersistentFlags().StringVar(&cfg.StorageClassName, "storage-class-name", "",
		"If set, only PVCs using this exact StorageClass name will get labels injected. Mutually exclusive with --storage-class-name-regex.")
	c.PersistentFlags().StringVar(&cfg.StorageClassNameRegex, "storage-class-name-regex", "",
		"If set, only PVCs whose StorageClass name matches this regex will get labels injected. Mutually exclusive with --storage-class-name.")
	c.PersistentFlags().StringVar(&cfg.PVCNameRegex, "pvc-name-regex", "",
		"If set, only PVCs whose name matches this regex will get labels injected.")
	c.PersistentFlags().StringVar(&cfg.CSIDriverName, "csi-driver-name", "",
		"Only PVCs whose StorageClass provisioner equals this CSI driver name are processed (e.g. csi.vastdata.com). Mutually exclusive with --csi-driver-name-regex.")
	c.PersistentFlags().StringVar(&cfg.CSIDriverNameRegex, "csi-driver-name-regex", "",
		"Only PVCs whose StorageClass provisioner matches this regex are processed (e.g. \".*vastdata.*\"). Mutually exclusive with --csi-driver-name.")
	c.MarkFlagsMutuallyExclusive("storage-class-name", "storage-class-name-regex")
	c.MarkFlagsMutuallyExclusive("csi-driver-name", "csi-driver-name-regex")
}

// configure registers admission webhooks on the shared manager.
func configure(cmd *cobra.Command, sharedMgr *manager.SharedManager, cfg *config.Config) {
	cmd.PreRunE = func(c *cobra.Command, args []string) error {
		if cfg.StorageClassName != "" && cfg.StorageClassNameRegex != "" {
			return fmt.Errorf("--storage-class-name and --storage-class-name-regex are mutually exclusive")
		}
		if cfg.CSIDriverName != "" && cfg.CSIDriverNameRegex != "" {
			return fmt.Errorf("--csi-driver-name and --csi-driver-name-regex are mutually exclusive")
		}
		if cfg.StorageClassNameRegex != "" {
			if _, err := regexp.Compile(cfg.StorageClassNameRegex); err != nil {
				return fmt.Errorf("invalid --storage-class-name-regex %q: %w", cfg.StorageClassNameRegex, err)
			}
		}
		if cfg.PVCNameRegex != "" {
			if _, err := regexp.Compile(cfg.PVCNameRegex); err != nil {
				return fmt.Errorf("invalid --pvc-name-regex %q: %w", cfg.PVCNameRegex, err)
			}
		}
		if cfg.CSIDriverNameRegex != "" {
			if _, err := regexp.Compile(cfg.CSIDriverNameRegex); err != nil {
				return fmt.Errorf("invalid --csi-driver-name-regex %q: %w", cfg.CSIDriverNameRegex, err)
			}
		}
		if cfg.PvcLabelWebhookEnabled && cfg.CSIDriverName == "" && cfg.CSIDriverNameRegex == "" {
			return fmt.Errorf("PVC label webhook requires --csi-driver-name or --csi-driver-name-regex")
		}
		return nil
	}
	cmd.Run = func(c *cobra.Command, args []string) {
		opts := zap.Options{Development: false}
		ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

		// Get TLS options for webhook server
		enableHTTP2, _ := c.Root().PersistentFlags().GetBool("enable-http2")
		var webhookTLSOpts []func(*tls.Config)
		if !enableHTTP2 {
			webhookTLSOpts = append(webhookTLSOpts, func(c *tls.Config) {
				c.NextProtos = []string{"http/1.1"}
			})
		}

		var webhookCertWatcher *certwatcher.CertWatcher
		if len(cfg.WebhookCertPath) > 0 {
			var err error
			webhookCertWatcher, err = certwatcher.New(
				filepath.Join(cfg.WebhookCertPath, cfg.WebhookCertName),
				filepath.Join(cfg.WebhookCertPath, cfg.WebhookCertKey),
			)
			if err != nil {
				setupLog.Error(err, "Failed to initialize webhook certificate watcher")
				os.Exit(1)
			}

			webhookTLSOpts = append(webhookTLSOpts, func(config *tls.Config) {
				config.GetCertificate = webhookCertWatcher.GetCertificate
			})
		}

		webhookServer := ctrlwebhook.NewServer(ctrlwebhook.Options{
			TLSOpts: webhookTLSOpts,
		})

		// Get the shared manager instance with webhook server option
		mgr, err := sharedMgr.Get(func(opts *ctrl.Options) {
			opts.WebhookServer = webhookServer
		})
		if err != nil {
			panic(err)
		}

		// Get the zap logger from shared manager
		logger := sharedMgr.GetLogger()
		rainbow := logging.New(logger, cfg.DevLogging)

		// Create k8sClient using factory
		factory := k8s_client.NewFactory("extensions-controller")
		k8sClient, err := factory.K8sClientForController(mgr.GetClient(), logger)
		if err != nil {
			panic(err)
		}

		if cfg.PvcLabelWebhookEnabled {
			if err := pvcwebhook.SetupWithManager(mgr, k8sClient, cfg, rainbow); err != nil {
				panic(err)
			}
		}

		if cfg.VSCRValidationWebhookEnabled || cfg.VVRValidationWebhookEnabled {
			pvcwebhook.SetupReplicationCRDValidationWebhooks(
				mgr, k8sClient, cfg.SSLVerify, rainbow,
				cfg.VSCRValidationWebhookEnabled, cfg.VVRValidationWebhookEnabled,
			)
		}

		if webhookCertWatcher != nil {
			if err := mgr.Add(webhookCertWatcher); err != nil {
				panic(err)
			}
		}
	}
}
