package server

import (
	"github.com/spf13/cobra"
	"k8s.io/client-go/kubernetes"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	grpcserver "github.com/vast-data/vast-csi/extensions-controller/internal/server"
	"github.com/vast-data/vast-csi/extensions-controller/internal/server/extensions"
)

// RegisterFlags registers VastExtensions gRPC server flags with the cobra command.
func RegisterFlags(c *cobra.Command, cfg *config.Config) {
	c.PersistentFlags().StringVar(&cfg.ExtensionsGRPCBindAddress, "extensions-grpc-bind-address", grpcserver.DefaultExtensionsGRPCBindAddress,
		"Listen address for the VastExtensions gRPC API.")
}

func configure(cmd *cobra.Command, sharedMgr *manager.SharedManager, cfg *config.Config) {
	cmd.Run = func(c *cobra.Command, args []string) {
		logger := sharedMgr.GetLogger()

		mgr, err := sharedMgr.Get()
		if err != nil {
			panic(err)
		}

		factory := k8s_client.NewFactory("extensions-controller")
		k8sClient, err := factory.K8sClientForController(mgr.GetClient(), logger)
		if err != nil {
			panic(err)
		}

		kubeClient, err := kubernetes.NewForConfig(mgr.GetConfig())
		if err != nil {
			panic(err)
		}

		grpcSrv := grpcserver.New(cfg.ExtensionsGRPCBindAddress, kubeClient, logger)
		grpcSrv.RegisterService(extensions.NewService(k8sClient, cfg.SSLVerify, logger, logging.New(logger, cfg.DevLogging)))
		if err := mgr.Add(grpcSrv); err != nil {
			panic(err)
		}
	}
}
