package cosi

import (
	"github.com/spf13/cobra"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/namespace"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
)

type module struct{}

// NS is the COSI manager namespace.
var NS namespace.Namespace = module{}

func (module) Name() string  { return "cosi" }
func (module) Short() string { return "COSI extensions" }
func (module) Long() string {
	return "Run COSI-related controllers for the VAST object storage driver."
}

func (module) RegisterFlags(cmd *cobra.Command, cfg *config.Config) {}

func (module) Configure(ctx namespace.Context, cmd *cobra.Command) {
	configure(cmd, ctx.SharedMgr)
}
