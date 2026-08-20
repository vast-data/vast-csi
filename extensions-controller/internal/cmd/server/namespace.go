package server

import (
	"github.com/spf13/cobra"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/namespace"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
)

type module struct{}

// NS is the VastExtensions gRPC server namespace.
var NS namespace.Namespace = module{}

func (module) Name() string  { return "server" }
func (module) Short() string { return "VastExtensions gRPC API" }
func (module) Long() string {
	return "Run the VastExtensions gRPC API."
}

func (module) RegisterFlags(cmd *cobra.Command, cfg *config.Config) {
	RegisterFlags(cmd, cfg)
}

func (module) Configure(ctx namespace.Context, cmd *cobra.Command) {
	configure(cmd, ctx.SharedMgr, ctx.Config)
}
