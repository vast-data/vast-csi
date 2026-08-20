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

package replication

import (
	"github.com/go-logr/zapr"
	"github.com/spf13/cobra"
	"k8s.io/client-go/kubernetes"
	ctrl "sigs.k8s.io/controller-runtime"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/logging"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/utils"
	"github.com/vast-data/vast-csi/extensions-controller/internal/controller"
	"github.com/vast-data/vast-csi/extensions-controller/internal/server"
	"github.com/vast-data/vast-csi/extensions-controller/internal/server/extensions"
)

// RegisterFlags registers replication object controller flags with the cobra command.
func RegisterFlags(c *cobra.Command, cfg *config.Config) {
	c.Flags().BoolVar(&cfg.ApplyExistingPVCs, "apply-existing-pvcs", false,
		"Inject storageClass (and subsystem for block) labels onto existing PVCs whose "+
			"backing VAST object appears in the VolumeMapping for the reconciled StorageClass. "+
			"Mirrors what the PVC label webhook does for newly created PVCs. "+
			"Idempotent: PVCs that already carry both labels are skipped.")
	// Name format flags
	c.Flags().StringVar(&cfg.PVCNameFormat, "pvc-name-format", common.DefaultPVCNameFormat,
		`Format string for destination PVC names. Available tokens:
  {pvc_name}            - full source PVC name
  {pvc_name_suf:<N>}    - last N characters of source PVC name
  {pvc_name_pref:<N>}   - first N characters of source PVC name
  {endpoint}            - VAST endpoint (slugified)
  {sc_name}             - destination StorageClass name
  {sc_name_suf:<N>}     - last N characters of StorageClass name
  {sc_name_pref:<N>}    - first N characters of StorageClass name`)

	c.Flags().StringVar(&cfg.PVNameFormat, "pv-name-format", common.DefaultPVNameFormat,
		`Format string for destination PV names. Available tokens:
  {pv_name}             - full source PV name
  {pv_name_suf:<N>}     - last N characters of source PV name
  {pv_name_pref:<N>}    - first N characters of source PV name
  {endpoint}            - VAST endpoint (slugified)
  {sc_name}             - destination StorageClass name
  {sc_name_suf:<N>}     - last N characters of StorageClass name
  {sc_name_pref:<N>}    - first N characters of StorageClass name`)

	c.Flags().StringVar(&cfg.VolumeReplicationNameFormat, "volume-replication-name-format", "{vr_name}-repl-{endpoint}",
		`Format string for destination VolumeReplication CRD names. Available tokens:
  {vr_name}             - full source VolumeReplication name
  {vr_name_suf:<N>}     - last N characters of source VolumeReplication name
  {vr_name_pref:<N>}    - first N characters of source VolumeReplication name
  {vr_namespace}        - source VolumeReplication namespace
  {endpoint}            - VAST endpoint (slugified)
  {sc_name}             - destination StorageClass name
  {sc_name_suf:<N>}     - last N characters of StorageClass name
  {sc_name_pref:<N>}    - first N characters of StorageClass name`)

	c.Flags().StringVar(&cfg.VolumeGroupReplicationNameFormat, "volume-group-replication-name-format", "{vgr_name}-repl-{endpoint}",
		`Format string for destination VolumeGroupReplication CRD names. Available tokens:
  {vgr_name}            - full source VolumeGroupReplication name
  {vgr_name_suf:<N>}    - last N characters of source VolumeGroupReplication name
  {vgr_name_pref:<N>}   - first N characters of source VolumeGroupReplication name
  {vgr_namespace}       - source VolumeGroupReplication namespace
  {endpoint}            - VAST endpoint (slugified)
  {sc_name}             - destination StorageClass name
  {sc_name_suf:<N>}     - last N characters of StorageClass name
  {sc_name_pref:<N>}    - first N characters of StorageClass name`)

	c.Flags().StringVar(&cfg.ExtensionsGRPCBindAddress, "extensions-grpc-bind-address", server.DefaultExtensionsGRPCBindAddress,
		"Address the VastExtensions gRPC API binds to. TCP (e.g. :9090) always uses TLS and "+
			"TokenReview of the caller's ServiceAccount token. Use an absolute unix socket path "+
			"for co-located sidecars (plaintext, pod-local).")
}

// NewCommand creates the "replication-object" Cobra subcommand that runs the
// unified replication object controller for both VolumeReplication and
// VolumeGroupReplication resources.
func NewCommand(sharedMgr *manager.SharedManager, cfg *config.Config) *cobra.Command {
	c := &cobra.Command{
		Use:   "replication",
		Short: "Run the replication object controller for VolumeReplication and VolumeGroupReplication",
		Long: `Start a controller-runtime manager that runs the unified replication object controller.
This controller watches both VolumeReplication and VolumeGroupReplication resources and manages
VastReplicationContent objects that handle creation of destination PV+PVC pairs, VAST volumes,
VolumeReplicationClass/VolumeGroupReplicationClass, and mirrored VolumeReplication/VolumeGroupReplication CRDs.`,
		Run: func(c *cobra.Command, args []string) {
			// Use the same shared zap logger for ctrl.Log so that controller-runtime
			// output (controllers, health server, etc.) has identical formatting to
			// the gRPC server and other components.
			ctrl.SetLogger(zapr.NewLogger(sharedMgr.GetLogger()))

			if err := utils.ValidateNameFormat(cfg.PVCNameFormat, "pvc"); err != nil {
				panic(err)
			}
			if err := utils.ValidateNameFormat(cfg.PVNameFormat, "pv"); err != nil {
				panic(err)
			}

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

			if err := controller.SetupReplicationObjectProvisionerController(mgr, k8sClient, logger, cfg); err != nil {
				panic(err)
			}

			if err := controller.SetupVastReplicationContentController(mgr, k8sClient, logger, cfg); err != nil {
				panic(err)
			}

			if err := controller.SetupVastStorageClassReplicationController(mgr, k8sClient, logger, cfg); err != nil {
				panic(err)
			}

			if err := controller.SetupVastVolumeReplicationController(mgr, k8sClient, logger, cfg); err != nil {
				panic(err)
			}

			if err := controller.SetupPVCRemapController(mgr, k8sClient, logger, cfg); err != nil {
				panic(err)
			}

			kubeClient, err := kubernetes.NewForConfig(mgr.GetConfig())
			if err != nil {
				panic(err)
			}

			grpcSrv := server.New(cfg.ExtensionsGRPCBindAddress, kubeClient, logger)
			grpcSrv.RegisterService(extensions.NewService(k8sClient, cfg.SSLVerify, logger, logging.New(logger, cfg.DevLogging)))
			if err := mgr.Add(grpcSrv); err != nil {
				panic(err)
			}
		},
	}

	RegisterFlags(c, cfg)

	return c
}
