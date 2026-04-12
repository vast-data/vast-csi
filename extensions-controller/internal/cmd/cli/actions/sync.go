package actions

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewSyncCommand returns the `vastrep sync` subcommand.
func NewSyncCommand(mgr manager.Manager, bin string) *cobra.Command {
	var (
		vscrName  string
		vvrName   string
		namespace string
	)

	cmd := &cobra.Command{
		Use:   "sync",
		Short: "Trigger a resync on a replication object",
		Long: fmt.Sprintf(`Request an immediate resync (re-synchronisation) of a VastStorageClassReplication
or VastVolumeReplication object.

Examples:
  %[1]s sync --vscr my-repl
  %[1]s sync --vvr  my-vol -n staging`, bin),
		RunE: func(cmd *cobra.Command, args []string) error {
			if vscrName == "" && vvrName == "" {
				return fmt.Errorf("must specify --vscr <name> or --vvr <name>")
			}
			if vscrName != "" && vvrName != "" {
				return fmt.Errorf("--vscr and --vvr are mutually exclusive")
			}

			k8s, err := mgr.GetK8sClient()
			if err != nil {
				return err
			}

			kind, name := "vscr", vscrName
			if vvrName != "" {
				kind, name = "vvr", vvrName
			}
			fmt.Printf("%s Requesting resync on %s/%s ...\n", cli.Cyan("→"), kind, cli.Bold(name))

			if err := cli.UpdateReplicationSpec(context.Background(), k8s, vscrName, vvrName, namespace,
				vastv1alpha1.ActionResync, ""); err != nil {
				return fmt.Errorf("sync failed: %w", err)
			}

			fmt.Printf("%s Resync action set on %s/%s\n", cli.Green("✓"), kind, cli.Bold(name))
			return nil
		},
	}

	cmd.Flags().StringVar(&vscrName, "vscr", "", "Name of the VastStorageClassReplication")
	cmd.Flags().StringVar(&vvrName, "vvr", "", "Name of the VastVolumeReplication")
	cmd.Flags().StringVarP(&namespace, "namespace", "n", "default", "Kubernetes namespace")

	return cmd
}
