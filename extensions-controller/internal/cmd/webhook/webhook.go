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
	c.Flags().BoolVar(&cfg.PvcLabelWebhookEnabled, "enable-pvc-label-webhook", false,
		"Enable the PVC label injection webhook")

	// Webhook flags
	c.Flags().StringVar(&cfg.WebhookCertPath, "webhook-cert-path", "/tmp/k8s-webhook-server/serving-certs",
		"The directory that contains the webhook TLS certificate and key files.")
	c.Flags().StringVar(&cfg.WebhookCertName, "webhook-cert-name", "tls.crt",
		"The name of the webhook certificate file.")
	c.Flags().StringVar(&cfg.WebhookCertKey, "webhook-cert-key", "tls.key",
		"The name of the webhook key file.")
	c.Flags().StringVar(&cfg.StorageClassName, "storage-class-name", "",
		"If set, only PVCs using this exact StorageClass name will get labels injected. Mutually exclusive with --storage-class-name-regex.")
	c.Flags().StringVar(&cfg.StorageClassNameRegex, "storage-class-name-regex", "",
		"If set, only PVCs whose StorageClass name matches this regex will get labels injected. Mutually exclusive with --storage-class-name.")
	c.Flags().StringVar(&cfg.PVCNameRegex, "pvc-name-regex", "",
		"If set, only PVCs whose name matches this regex will get labels injected.")
	c.Flags().StringVar(&cfg.CSIDriverName, "csi-driver-name", "",
		"If set, only PVCs whose StorageClass provisioner matches this CSI driver name will get labels injected (e.g. csi.vastdata.com).")
	c.MarkFlagsMutuallyExclusive("storage-class-name", "storage-class-name-regex")
}

func NewCommand(sharedMgr *manager.SharedManager, cfg *config.Config) *cobra.Command {
	c := &cobra.Command{
		Use:   "pvc-label-webhook",
		Short: "Run the PVC label injection webhook server",
		Long: `Start a mutating admission webhook that automatically injects
replication-related labels onto PVCs at creation time based on StorageClass
parameters (subsystem, volumeGroup, storageClass).`,
		PreRunE: func(c *cobra.Command, args []string) error {
			if cfg.StorageClassName != "" && cfg.StorageClassNameRegex != "" {
				return fmt.Errorf("--storage-class-name and --storage-class-name-regex are mutually exclusive")
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
			return nil
		},
		Run: func(c *cobra.Command, args []string) {
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

			pvcwebhook.SetupReplicationCRDValidationWebhooks(mgr, k8sClient, cfg.SSLVerify, rainbow)

			if webhookCertWatcher != nil {
				if err := mgr.Add(webhookCertWatcher); err != nil {
					panic(err)
				}
			}
		},
	}

	RegisterFlags(c, cfg)

	return c
}
