package actions

import (
	"context"
	"fmt"
	"strings"

	"github.com/spf13/cobra"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewStatusCommand returns the `vastrep status` subcommand.
func NewStatusCommand(mgr manager.Manager, bin string) *cobra.Command {
	var (
		vscrName  string
		vvrName   string
		namespace string
	)

	cmd := &cobra.Command{
		Use:   "status",
		Short: "Show replication status of a VSCR or VVR object",
		Long: fmt.Sprintf(`Display the spec and status of a VastStorageClassReplication or
VastVolumeReplication object in a human-readable form.

Examples:
  %[1]s status --vscr my-repl
  %[1]s status --vvr  my-vol -n staging`, bin),
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

			if vscrName != "" {
				obj, err := k8s.GetVastStorageClassReplication(ctx, vscrName, namespace)
				if err != nil {
					return fmt.Errorf("VastStorageClassReplication %s/%s not found: %w", namespace, vscrName, err)
				}
				printVSCRStatus(obj)
			} else {
				obj, err := k8s.GetVastVolumeReplication(ctx, vvrName, namespace)
				if err != nil {
					return fmt.Errorf("VastVolumeReplication %s/%s not found: %w", namespace, vvrName, err)
				}
				printVVRStatus(obj)
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&vscrName, "vscr", "", "Name of the VastStorageClassReplication")
	cmd.Flags().StringVar(&vvrName, "vvr", "", "Name of the VastVolumeReplication")
	cmd.Flags().StringVarP(&namespace, "namespace", "n", "default", "Kubernetes namespace")

	return cmd
}

func printVSCRStatus(obj *vastv1alpha1.VastStorageClassReplication) {
	fmt.Printf("%s  %s/%s\n", cli.Bold("VastStorageClassReplication"), obj.Namespace, cli.Cyan(obj.Name))
	fmt.Println(strings.Repeat("─", 60))
	fmt.Printf("  %-28s %s\n", "Primary StorageClass:", highlightPrimary(obj.Spec.PrimaryStorageClass))
	printAction("Failover Type", string(obj.Spec.FailoverType))
	if obj.Spec.Resync {
		fmt.Printf("  %-28s %s\n", "Resync:", cli.Yellow("pending"))
	}
	fmt.Printf("  %-28s %d cluster(s), %d target(s)\n", "Topology:", len(obj.Spec.AllStorageClasses()), len(obj.Spec.ProtectionTopology))
	for _, t := range obj.Spec.ProtectionTopology {
		printTopologyTarget(t.Source, t.Destination, t.PeerName)
	}
	if secs, err := obj.Spec.EffectiveSyncIntervalSeconds(); err == nil {
		fmt.Printf("  %-28s %ds\n", "Sync Interval:", secs)
	}
	fmt.Printf("  %-28s %s\n", "PVC Remap:", boolStr(obj.Spec.PVCRemap))
	fmt.Printf("  %-28s %s\n", "Sync PVC/PV:", boolStr(obj.Spec.SyncPVCPV))
	fmt.Printf("  %-28s %s\n", "Vol Reclaim Policy:", destVolReclaimStr(obj.Spec.DestVolReclaimPolicy))
	printProtectionPolicyTemplate(obj.Spec.ProtectionPolicyTemplate)
	printStorageClassList(obj.Spec.AllStorageClasses())
	fmt.Println()
	fmt.Printf("  %s\n", cli.Bold("Status:"))
	if obj.Status.CurrentPrimaryStorageClass != "" {
		fmt.Printf("  %-28s %s\n", "Current Primary:", highlightPrimary(obj.Status.CurrentPrimaryStorageClass))
	}
	if obj.Status.PpathName != "" {
		fmt.Printf("  %-28s %s\n", "Ppath Name:", obj.Status.PpathName)
	}
	if len(obj.Status.PpathDirMapping) > 0 {
		fmt.Printf("  %-28s\n", "Ppath Dir Mapping:")
		for sc, dir := range obj.Status.PpathDirMapping {
			fmt.Printf("    %-26s %s\n", sc+":", dir)
		}
	}
	printAction("Last Failover Type", string(obj.Status.LastFailoverType))
	printSyncStatus(obj.Status.SyncStatus)
}

func printVVRStatus(obj *vastv1alpha1.VastVolumeReplication) {
	fmt.Printf("%s  %s/%s\n", cli.Bold("VastVolumeReplication"), obj.Namespace, cli.Cyan(obj.Name))
	fmt.Println(strings.Repeat("─", 60))
	fmt.Printf("  %-28s %s\n", "Volume (PVC):", cli.Bold(obj.Spec.VolumeName))
	fmt.Printf("  %-28s %s\n", "Storage Classes:", vastv1alpha1.DisplayableList(obj.Spec.AllStorageClasses()).String())
	fmt.Printf("  %-28s %s\n", "Primary StorageClass:", highlightPrimary(obj.Spec.PrimaryStorageClass))
	printAction("Failover Type", string(obj.Spec.FailoverType))
	if obj.Spec.Resync {
		fmt.Printf("  %-28s %s\n", "Resync:", cli.Yellow("pending"))
	}
	fmt.Printf("  %-28s %d cluster(s), %d target(s)\n", "Topology:", len(obj.Spec.AllStorageClasses()), len(obj.Spec.ProtectionTopology))
	for _, t := range obj.Spec.ProtectionTopology {
		printTopologyTarget(t.Source, t.Destination, t.PeerName)
	}
	if secs, err := obj.Spec.EffectiveSyncIntervalSeconds(); err == nil {
		fmt.Printf("  %-28s %ds\n", "Sync Interval:", secs)
	}
	fmt.Printf("  %-28s %s\n", "PVC Remap:", boolStr(obj.Spec.PVCRemap))
	fmt.Printf("  %-28s %s\n", "Vol Reclaim Policy:", destVolReclaimStr(obj.Spec.DestVolReclaimPolicy))
	printProtectionPolicyTemplate(obj.Spec.ProtectionPolicyTemplate)
	fmt.Println()
	fmt.Printf("  %s\n", cli.Bold("Status:"))
	if obj.Status.CurrentPrimaryStorageClass != "" {
		fmt.Printf("  %-28s %s\n", "Current Primary:", highlightPrimary(obj.Status.CurrentPrimaryStorageClass))
	}
	if obj.Status.PpathName != "" {
		fmt.Printf("  %-28s %s\n", "Ppath Name:", obj.Status.PpathName)
	}
	if len(obj.Status.PpathDirMapping) > 0 {
		fmt.Printf("  %-28s\n", "Ppath Dir Mapping:")
		for sc, dir := range obj.Status.PpathDirMapping {
			fmt.Printf("    %-26s %s\n", sc+":", dir)
		}
	}
	printAction("Last Failover Type", string(obj.Status.LastFailoverType))
	printSyncStatus(obj.Status.SyncStatus)
}

func printStorageClassList(classes []string) {
	if len(classes) == 0 {
		return
	}
	fmt.Printf("  %-28s\n", "Storage Classes:")
	for _, sc := range classes {
		fmt.Printf("    - %s\n", sc)
	}
}

func highlightPrimary(sc string) string {
	if sc == "" {
		return cli.Yellow("(not set)")
	}
	return cli.Green(sc)
}

func printAction(label, action string) {
	if action == "" {
		return
	}
	fmt.Printf("  %-28s %s\n", label+":", action)
}

func printSyncStatus(s string) {
	if s == "" {
		return
	}
	var colored string
	switch s {
	case vastv1alpha1.SyncStatusCompleted:
		colored = cli.Green(s)
	case vastv1alpha1.SyncStatusInProgress:
		colored = cli.Cyan(s)
	case vastv1alpha1.SyncStatusUnreachable:
		colored = cli.Yellow(s)
	case vastv1alpha1.SyncStatusError:
		colored = cli.Red(s)
	case vastv1alpha1.SyncStatusInvalid:
		colored = cli.Red(s)
	default:
		colored = s
	}
	fmt.Printf("  %-28s %s\n", "Sync Status:", colored)
}

func boolStr(b bool) string {
	if b {
		return cli.Green("true")
	}
	return "false"
}

func printTopologyTarget(source, destination, peerName string) {
	line := fmt.Sprintf("%s → %s", cli.Cyan(source), cli.Cyan(destination))
	if peerName != "" {
		line += fmt.Sprintf("  (peer: %s)", peerName)
	}
	fmt.Printf("    %s\n", line)
}

func printProtectionPolicyTemplate(t vastv1alpha1.ProtectionPolicyTemplate) {
	fmt.Printf("  %-28s\n", "Protection Policy:")
	for i, f := range t.Params {
		parts := fmt.Sprintf("every=%s", f.Every)
		if f.KeepLocal != "" {
			parts += fmt.Sprintf(" keepLocal=%s", f.KeepLocal)
		}
		if f.KeepRemote != "" {
			parts += fmt.Sprintf(" keepRemote=%s", f.KeepRemote)
		}
		if f.StartAt != "" {
			parts += fmt.Sprintf(" startAt=%s", f.StartAt)
		}
		fmt.Printf("    %-24s %s\n", fmt.Sprintf("Frame[%d]:", i), parts)
	}
}
