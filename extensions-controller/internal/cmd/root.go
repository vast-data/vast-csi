package cmd

import (
	"flag"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cosi"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/namespace"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/replication"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/server"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/webhook"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/version"
	"k8s.io/klog/v2"
)

// operatorBinaryName is the well-known name used when the binary is deployed
// inside Kubernetes as a controller.  All other binary names are treated as
// the user-facing CLI.
const operatorBinaryName = "manager"

// IsOperator reports whether cmd is the in-cluster manager command tree.
func IsOperator(cmd *cobra.Command) bool {
	return cmd != nil && cmd.Use == operatorBinaryName
}

// NewCommand is the single entry-point.  It dispatches to a minimal CLI
// command tree or the full operator command tree depending on the binary name.
func NewCommand(name string) *cobra.Command {
	if name == operatorBinaryName {
		return newOperatorCommand(name)
	}
	return cli.NewCLICommand(name)
}

// newOperatorCommand builds the full operator command tree for in-cluster use.
func newOperatorCommand(name string) *cobra.Command {
	c := &cobra.Command{
		Use:   name,
		Short: "VAST extensions operator",
		Long:  "VAST extensions operator for the VAST CSI driver.",
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			noColor, _ := cmd.Root().PersistentFlags().GetBool("no-color")
			color.NoColor = noColor
			version.PrintVersion()
		},
		// Disable default cobra execution — main calls namespace.ExecuteNamespace instead.
		RunE: func(cmd *cobra.Command, args []string) error {
			return cmd.Help()
		},
	}

	c.PersistentFlags().Bool("no-color", false, "Disable colored output")

	cfg := new(config.Config)

	klog.InitFlags(flag.CommandLine)
	c.PersistentFlags().AddGoFlagSet(flag.CommandLine)
	manager.RegisterFlags(c, cfg)

	sharedMgr := manager.NewSharedManager(c, cfg)

	nsCtx := namespace.Context{
		SharedMgr: sharedMgr,
		Config:    cfg,
	}
	namespaces := []namespace.Namespace{replication.NS, server.NS, webhook.NS, cosi.NS}

	namespace.Attach(c, nsCtx, namespaces...)

	return c
}
