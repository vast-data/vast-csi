package actions

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/spf13/cobra"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/cli/client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/cmd/manager"
)

// NewListCommand returns the `vastrep list` subcommand.
func NewListCommand(mgr manager.Manager, bin string) *cobra.Command {
	var (
		namespace     string
		allNamespaces bool
	)

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List all VastStorageClassReplication and VastVolumeReplication objects",
		Long: fmt.Sprintf(`Display a summary table of all VSCR and VVR objects.

Examples:
  %[1]s list
  %[1]s list -n staging
  %[1]s list -A`, bin),
		RunE: func(cmd *cobra.Command, args []string) error {
			k8s, err := mgr.GetK8sClient()
			if err != nil {
				return err
			}
			ctx := context.Background()

			ns := namespace
			if allNamespaces {
				ns = ""
			}

			vscrs, err := k8s.ListVastStorageClassReplications(ctx, ns)
			if err != nil {
				return err
			}
			vvrs, err := k8s.ListVastVolumeReplications(ctx, ns)
			if err != nil {
				return err
			}

			if len(vscrs) == 0 && len(vvrs) == 0 {
				fmt.Println("No resources found.")
				return nil
			}

			printListTable(vscrs, vvrs)
			return nil
		},
	}

	cmd.Flags().StringVarP(&namespace, "namespace", "n", "default", "Kubernetes namespace")
	cmd.Flags().BoolVarP(&allNamespaces, "all-namespaces", "A", false, "List resources across all namespaces")

	return cmd
}

// listRow holds the plain (uncolored) cell values for one table row.
type listRow struct {
	kind           string
	namespace      string
	name           string
	scs            string
	primary        string
	action         string
	destVolReclaim string
	syncStatus     string
	age            string
}

func vscrRow(obj *vastv1alpha1.VastStorageClassReplication) listRow {
	primary := obj.Status.CurrentPrimaryStorageClass
	if primary == "" {
		primary = obj.Spec.PrimaryStorageClass
	}
	return listRow{
		kind:           "VSCR",
		namespace:      obj.Namespace,
		name:           obj.Name,
		scs:            vastv1alpha1.DisplayableList(obj.Spec.AllStorageClasses()).String(),
		primary:        primary,
		action:         actionStr(string(obj.Spec.FailoverType)),
		destVolReclaim: destVolReclaimStr(obj.Spec.DestVolReclaimPolicy),
		syncStatus:     syncStatusStr(obj.Status.SyncStatus),
		age:            age(obj.CreationTimestamp.Time),
	}
}

func vvrRow(obj *vastv1alpha1.VastVolumeReplication) listRow {
	primary := obj.Status.CurrentPrimaryStorageClass
	if primary == "" {
		primary = obj.Spec.PrimaryStorageClass
	}
	return listRow{
		kind:           "VVR",
		namespace:      obj.Namespace,
		name:           obj.Name,
		scs:            vastv1alpha1.DisplayableList(obj.Spec.AllStorageClasses()).String(),
		primary:        primary,
		action:         actionStr(string(obj.Spec.FailoverType)),
		destVolReclaim: destVolReclaimStr(obj.Spec.DestVolReclaimPolicy),
		syncStatus:     syncStatusStr(obj.Status.SyncStatus),
		age:            age(obj.CreationTimestamp.Time),
	}
}

func actionStr(a string) string {
	if a == "" {
		return "-"
	}
	return a
}

// printListTable builds rows, computes max column widths from plain text, then
// prints each row with manual padding so ANSI color codes don't shift columns.
func printListTable(vscrs []vastv1alpha1.VastStorageClassReplication, vvrs []vastv1alpha1.VastVolumeReplication) {
	headers := []string{"KIND", "NAMESPACE", "NAME", "STORAGE CLASSES", "PRIMARY", "FAILOVER TYPE", "VOL RECLAIM POLICY", "SYNC STATUS", "AGE"}

	rows := make([]listRow, 0, len(vscrs)+len(vvrs))
	for i := range vscrs {
		rows = append(rows, vscrRow(&vscrs[i]))
	}
	for i := range vvrs {
		rows = append(rows, vvrRow(&vvrs[i]))
	}

	// Compute column widths from plain text only.
	widths := make([]int, len(headers))
	for i, h := range headers {
		widths[i] = len(h)
	}
	for _, r := range rows {
		cols := rowCols(r)
		for i, c := range cols {
			if len(c) > widths[i] {
				widths[i] = len(c)
			}
		}
	}

	const gap = 2

	pad := func(n int) string {
		if n <= 0 {
			return ""
		}
		return strings.Repeat(" ", n)
	}

	printPlainRow := func(cols []string) {
		var sb strings.Builder
		for i, c := range cols {
			sb.WriteString(c)
			if i < len(cols)-1 {
				sb.WriteString(pad(widths[i] - len(c) + gap))
			}
		}
		fmt.Println(sb.String())
	}

	printColorRow := func(r listRow) {
		cols := rowCols(r)
		colored := []string{
			client.Bold(cols[0]),  // KIND
			cols[1],            // NAMESPACE
			client.Cyan(cols[2]),  // NAME
			cols[3],            // STORAGE CLASSES
			client.Green(cols[4]), // PRIMARY
			cols[5],            // FAILOVER TYPE
			cols[6],
			client.SyncStatus(r.syncStatus),
			cols[8], // AGE
		}
		var sb strings.Builder
		for i, c := range colored {
			sb.WriteString(c)
			if i < len(colored)-1 {
				// Pad using the plain text width, not the colored string length.
				plainLen := len(cols[i])
				sb.WriteString(strings.Repeat(" ", widths[i]-plainLen+gap))
			}
		}
		fmt.Println(sb.String())
	}

	// Header line.
	printPlainRow(headers)

	// Separator — one continuous ─ rule spanning the full table width.
	totalWidth := gap * (len(headers) - 1)
	for _, w := range widths {
		totalWidth += w
	}
	fmt.Println(strings.Repeat("─", totalWidth))

	for _, r := range rows {
		printColorRow(r)
	}
}

func rowCols(r listRow) []string {
	return []string{r.kind, r.namespace, r.name, r.scs, r.primary, r.action, r.destVolReclaim, r.syncStatus, r.age}
}

func destVolReclaimStr(p vastv1alpha1.DestVolReclaimPolicy) string {
	if p == "" {
		return string(vastv1alpha1.DestVolReclaimPolicyRetain)
	}
	return string(p)
}

func syncStatusStr(s string) string {
	if s == "" {
		return "-"
	}
	return s
}

func age(t time.Time) string {
	if t.IsZero() {
		return "-"
	}
	d := time.Since(t).Round(time.Second)
	switch {
	case d < time.Minute:
		return fmt.Sprintf("%ds", int(d.Seconds()))
	case d < time.Hour:
		return fmt.Sprintf("%dm", int(d.Minutes()))
	case d < 24*time.Hour:
		return fmt.Sprintf("%dh", int(d.Hours()))
	default:
		return fmt.Sprintf("%dd", int(d.Hours()/24))
	}
}
