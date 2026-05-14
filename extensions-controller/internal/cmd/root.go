package cmd

import (
	"flag"
	"fmt"

	"github.com/fatih/color"
	"github.com/spf13/cobra"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli/actions"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/replication"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/webhook"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/config"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/version"
	"k8s.io/klog/v2"
)

// operatorBinaryName is the well-known name used when the binary is deployed
// inside Kubernetes as a controller.  All other binary names are treated as
// the user-facing CLI.
const operatorBinaryName = "manager"

// NewCommand is the single entry-point.  It dispatches to a minimal CLI
// command tree or the full operator command tree depending on the binary name.
func NewCommand(name string) *cobra.Command {
	if name == operatorBinaryName {
		return newOperatorCommand(name)
	}
	return newCLICommand(name)
}

// newCLICommand builds a lean command tree for end-user invocations.
// It registers only the flags that are relevant to CLI usage and does NOT
// start a controller-runtime manager.
func newCLICommand(name string) *cobra.Command {
	c := &cobra.Command{
		Use:   name,
		Short: "VAST CSI replication CLI",
		Long: fmt.Sprintf(`%[1]s is a CLI tool for managing VAST CSI volume replication.

Commands:
  %[1]s list                          list all VSCR and VVR objects
  %[1]s status     --vscr <name>      show detailed status of a single object
  %[1]s failover   --vscr <name> [--manner graceful|ungraceful] [--primary <sc>]
  %[1]s sync       --vscr <name>
  %[1]s delete     --vscr <name> [--yes]

Use %[1]s <command> --help for detailed usage of each command.`, name),
		SilenceUsage:  true, // don't dump usage on every error
		SilenceErrors: true, // let CheckError print it in color instead
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			noColor, _ := cmd.Root().PersistentFlags().GetBool("no-color")
			color.NoColor = noColor
		},
	}

	manager.RegisterCLIFlags(c)

	cliMgr := manager.NewCLIManager(c)

	c.AddCommand(
		actions.NewListCommand(cliMgr, name),
		actions.NewFailoverCommand(cliMgr, name),
		actions.NewSyncCommand(cliMgr, name),
		actions.NewStatusCommand(cliMgr, name),
		actions.NewDeleteCommand(cliMgr, name),
	)

	return c
}

// newOperatorCommand builds the full operator command tree for in-cluster use.
// It registers all controller flags, klog flags, and the hidden replication /
// webhook subcommands.  CLI action subcommands are NOT included here — the
// operator binary is not meant for interactive use.
func newOperatorCommand(name string) *cobra.Command {

	c := &cobra.Command{
		Use:   name,
		Short: "VAST CSI addons operator",
		Long: `VAST addons operator provides additional management capabilities alongside
the VAST CSI driver.  Features include PVC label injection webhook, destination
PVC controller, and volume replication controller.

Run individual subcommands to enable specific features.`,
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			noColor, _ := cmd.Root().PersistentFlags().GetBool("no-color")
			color.NoColor = noColor
			version.PrintVersion()
		},
	}

	c.PersistentFlags().Bool("no-color", false, "Disable colored output")

	cfg := new(config.Config)

	klog.InitFlags(flag.CommandLine)
	c.PersistentFlags().AddGoFlagSet(flag.CommandLine)
	manager.RegisterFlags(c, cfg)
	webhook.RegisterFlags(c, cfg)
	replication.RegisterFlags(c, cfg)

	sharedMgr := manager.NewSharedManager(c, cfg)

	c.AddCommand(
		replication.NewCommand(sharedMgr, cfg),
		webhook.NewCommand(sharedMgr, cfg),
	)

	c.PersistentPostRunE = func(cmd *cobra.Command, args []string) error {
		fmt.Println(cfg.Display(cmd.Name()))
		return sharedMgr.Start()
	}

	return c
}
