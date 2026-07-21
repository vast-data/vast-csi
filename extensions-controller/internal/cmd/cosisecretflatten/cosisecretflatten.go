package cosisecretflatten

import (
	"github.com/go-logr/zapr"
	"github.com/spf13/cobra"
	ctrl "sigs.k8s.io/controller-runtime"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cosi/credsflatten"
)

// NewCommand runs the COSI credentials flattener controller.
// Health, metrics, and max-concurrent-reconciles use shared manager persistent flags.
func NewCommand(sharedMgr *manager.SharedManager, cfg *config.Config) *cobra.Command {
	c := &cobra.Command{
		Use:   "cosi-secret-flatten",
		Short: "Flatten COSI BucketAccess credentials into Rook-style env vars",
		Long: `Watch annotated BucketAccess resources and create sibling *-flat Secret and
ConfigMap objects with AWS_* and BUCKET_* keys derived from the COSI BucketInfo JSON.

Enable per BucketAccess with annotation cosi.vastdata.com/flatten-credentials: "true".`,
		Run: func(c *cobra.Command, args []string) {
			ctrl.SetLogger(zapr.NewLogger(sharedMgr.GetLogger()))

			mgr, err := sharedMgr.Get()
			if err != nil {
				panic(err)
			}

			if err := credsflatten.SetupBucketAccessReconciler(mgr); err != nil {
				panic(err)
			}
		},
	}

	return c
}
