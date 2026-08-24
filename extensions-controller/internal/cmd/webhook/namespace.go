package webhook

import (
	"github.com/spf13/cobra"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/namespace"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
)

type module struct{}

// NS is the webhook manager namespace.
var NS namespace.Namespace = module{}

func (module) Name() string  { return "webhook" }
func (module) Short() string { return "Admission webhook servers" }
func (module) Long() string  { return "Run mutating and validating admission webhooks." }

func (module) RegisterFlags(cmd *cobra.Command, cfg *config.Config) {
	RegisterFlags(cmd, cfg)
}

func (module) Configure(ctx namespace.Context, cmd *cobra.Command) {
	configure(cmd, ctx.SharedMgr, ctx.Config)
}
