package cli

import (
	"fmt"

	"github.com/fatih/color"
	"github.com/spf13/cobra"

	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli/actions"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewCLICommand builds a lean command tree for end-user invocations.
// It registers only the flags that are relevant to CLI usage and does NOT
// start a controller-runtime manager.
func NewCLICommand(name string) *cobra.Command {
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
