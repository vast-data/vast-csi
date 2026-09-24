package actions

import (
	"context"
	"fmt"

	"github.com/spf13/cobra"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli/client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewFailoverCommand returns the `vastrep failover` subcommand.
func NewFailoverCommand(mgr manager.Manager, bin string) *cobra.Command {
	var (
		vscrName  string
		vvrName   string
		namespace string
		manner    string
		primary   string
	)

	cmd := &cobra.Command{
		Use:   "failover",
		Short: "Switch the primary StorageClass, optionally triggering a failover action",
		Long: fmt.Sprintf(`Switch the primary StorageClass on a VastStorageClassReplication or
VastVolumeReplication object.  --primary is required and must differ from the
current primary.

--manner is optional.  When provided, spec.action is set accordingly so the
controller also executes the corresponding failover operation.

Examples:
  %[1]s failover --vscr my-repl --primary sc-secondary
  %[1]s failover --vscr my-repl --primary sc-secondary --manner graceful
  %[1]s failover --vvr  my-vol  --primary sc-dr --manner ungraceful -n staging`, bin),
		RunE: func(cmd *cobra.Command, args []string) error {
			if vscrName == "" && vvrName == "" {
				return fmt.Errorf("must specify --vscr <name> or --vvr <name>")
			}
			if vscrName != "" && vvrName != "" {
				return fmt.Errorf("--vscr and --vvr are mutually exclusive")
			}

			// --manner is optional; when given it must be a recognised value.
			var failoverType vastv1alpha1.FailoverAction
			if manner != "" {
				switch manner {
				case "graceful":
					failoverType = vastv1alpha1.FailoverTypeGraceful
				case "ungraceful":
					failoverType = vastv1alpha1.FailoverTypeUngraceful
				default:
					return fmt.Errorf("--manner must be 'graceful' or 'ungraceful', got %q", manner)
				}
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
			desc := "primary switch"
			if manner != "" {
				desc = manner + " failover"
			}
			fmt.Printf("%s Triggering %s on %s/%s ...\n", client.Cyan("→"), desc, kind, client.Bold(name))

			// Validate that the requested primary differs from the current one
			// and is a member of the protection topology.
			if vscrName != "" {
				obj, err := k8s.GetVastStorageClassReplication(ctx, vscrName, namespace)
				if err != nil {
					return fmt.Errorf("VastStorageClassReplication %s/%s not found: %w", namespace, vscrName, err)
				}
				if err := validateFailoverPrimary(primary, obj.Spec.PrimaryStorageClass, obj.Spec.AllStorageClasses()); err != nil {
					return err
				}
			} else {
				obj, err := k8s.GetVastVolumeReplication(ctx, vvrName, namespace)
				if err != nil {
					return fmt.Errorf("VastVolumeReplication %s/%s not found: %w", namespace, vvrName, err)
				}
				if err := validateFailoverPrimary(primary, obj.Spec.PrimaryStorageClass, obj.Spec.AllStorageClasses()); err != nil {
					return err
				}
			}
			if err := client.PatchReplicationSpec(ctx, k8s, vscrName, vvrName, namespace, failoverType, primary); err != nil {
				return fmt.Errorf("failover failed: %w", err)
			}

			msg := fmt.Sprintf("Primary StorageClass will switch to %s", client.Bold(primary))
			if failoverType != "" {
				msg += fmt.Sprintf("; failoverType set to %s", client.FailoverType(failoverType))
			}
			fmt.Printf("%s %s\n", client.Green("✓"), msg)
			return nil
		},
	}

	cmd.Flags().StringVar(&vscrName, "vscr", "", "Name of the VastStorageClassReplication")
	cmd.Flags().StringVar(&vvrName, "vvr", "", "Name of the VastVolumeReplication")
	cmd.Flags().StringVarP(&namespace, "namespace", "n", "default", "Kubernetes namespace")
	cmd.Flags().StringVar(&manner, "manner", "", "Failover manner: graceful or ungraceful (optional)")
	cmd.Flags().StringVar(&primary, "primary", "", "New primary StorageClass after failover")

	_ = cmd.MarkFlagRequired("primary")

	return cmd
}

// validateFailoverPrimary checks that primary is a known StorageClass in the
// topology and is not already the current primary.
func validateFailoverPrimary(primary, currentPrimary string, all []string) error {
	if primary == currentPrimary {
		return fmt.Errorf("cannot failover: %q is already the primary StorageClass", primary)
	}
	for _, sc := range all {
		if sc == primary {
			return nil
		}
	}
	// Build the list of valid candidates (all except the current primary).
	candidates := make([]string, 0, len(all)-1)
	for _, sc := range all {
		if sc != currentPrimary {
			candidates = append(candidates, sc)
		}
	}
	return fmt.Errorf("StorageClass %q is not part of the replication topology\navailable options: %s",
		primary, vastv1alpha1.DisplayableList(candidates).String())
}
