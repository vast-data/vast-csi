package cosi

import (
	"github.com/go-logr/zapr"
	"github.com/spf13/cobra"
	ctrl "sigs.k8s.io/controller-runtime"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/controller"
)

func configure(cmd *cobra.Command, sharedMgr *manager.SharedManager) {
	cmd.Run = func(c *cobra.Command, args []string) {
		ctrl.SetLogger(zapr.NewLogger(sharedMgr.GetLogger()))

		mgr, err := sharedMgr.Get()
		if err != nil {
			panic(err)
		}

		// Requires objectstorage.k8s.io CRDs — only safe when cosi namespace is active.
		if err := k8s_client.RegisterCOSIBucketIDIndex(c.Context(), mgr.GetFieldIndexer()); err != nil {
			panic(err)
		}

		if err := controller.SetupCredentialsFlattenerController(mgr); err != nil {
			panic(err)
		}
	}
}
