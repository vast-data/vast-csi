package actions

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli/client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewDeleteCommand returns the `vastrep delete` subcommand.
func NewDeleteCommand(mgr manager.Manager, bin string) *cobra.Command {
	var (
		vscrName  string
		vvrName   string
		namespace string
		yes       bool
	)

	cmd := &cobra.Command{
		Use:   "delete",
		Short: "Delete a VastStorageClassReplication or VastVolumeReplication object",
		Long: fmt.Sprintf(`Delete a VSCR or VVR object.  The controller's finalizer keeps it alive
until all owned resources (destination PVCs, VAST objects, VRCs) have been
cleaned up; the object is fully removed once that process completes.

A confirmation prompt is shown unless --yes is passed.

Examples:
  %[1]s delete --vscr my-repl
  %[1]s delete --vvr  my-vol -n staging --yes`, bin),
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
			ctx := context.Background()

			kind, name := "vscr", vscrName
			if vvrName != "" {
				kind, name = "vvr", vvrName
			}

			if !yes {
				fmt.Printf("Delete %s/%s %s? [y/N] ", kind, client.Bold(name), client.Yellow("(this triggers cleanup of all owned resources)"))
				reader := bufio.NewReader(os.Stdin)
				answer, _ := reader.ReadString('\n')
				if strings.ToLower(strings.TrimSpace(answer)) != "y" {
					fmt.Println("Aborted.")
					return nil
				}
			}

			fmt.Printf("%s Deleting %s/%s ...\n", client.Cyan("→"), kind, client.Bold(name))

			if vscrName != "" {
				obj, err := k8s.GetVastStorageClassReplication(ctx, vscrName, namespace)
				if err != nil {
					return fmt.Errorf("VastStorageClassReplication %s/%s not found: %w", namespace, vscrName, err)
				}
				if err := k8s.DeleteVastStorageClassReplication(ctx, obj); err != nil {
					return err
				}
			} else {
				obj, err := k8s.GetVastVolumeReplication(ctx, vvrName, namespace)
				if err != nil {
					return fmt.Errorf("VastVolumeReplication %s/%s not found: %w", namespace, vvrName, err)
				}
				if err := k8s.DeleteVastVolumeReplication(ctx, obj); err != nil {
					return err
				}
			}

			fmt.Printf("%s Deletion request accepted for %s/%s\n", client.Green("✓"), kind, client.Bold(name))
			fmt.Printf("  The object will disappear once the controller finishes cleaning up owned resources.\n")
			return nil
		},
	}

	cmd.Flags().StringVar(&vscrName, "vscr", "", "Name of the VastStorageClassReplication")
	cmd.Flags().StringVar(&vvrName, "vvr", "", "Name of the VastVolumeReplication")
	cmd.Flags().StringVarP(&namespace, "namespace", "n", "default", "Kubernetes namespace")
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "Skip confirmation prompt")

	return cmd
}
