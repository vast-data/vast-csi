package client

import (
	"github.com/fatih/color"
	vastv1alpha1 "github.com/vast-data/vast-csi/extensions-controller/api/v1alpha1"
)

// Color helpers — enabled by default on TTY; root command may set color.NoColor = true.
var (
	Green  = color.New(color.FgGreen).SprintFunc()
	Yellow = color.New(color.FgYellow).SprintFunc()
	Red    = color.New(color.FgRed).SprintFunc()
	Cyan   = color.New(color.FgCyan).SprintFunc()
	Bold   = color.New(color.Bold).SprintFunc()
)

// FailoverType returns failoverType colored for terminal output.
func FailoverType(ft vastv1alpha1.FailoverAction) string {
	switch ft {
	case vastv1alpha1.FailoverTypeGraceful, vastv1alpha1.FailoverTypeUngraceful:
		return Yellow(string(ft))
	default:
		return string(ft)
	}
}

// SyncStatus returns sync status colored for terminal output.
func SyncStatus(s string) string {
	switch s {
	case vastv1alpha1.SyncStatusCompleted:
		return Green(s)
	case vastv1alpha1.SyncStatusInProgress:
		return Cyan(s)
	case vastv1alpha1.SyncStatusUnreachable:
		return Yellow(s)
	case vastv1alpha1.SyncStatusError:
		return Red(s)
	case vastv1alpha1.SyncStatusInvalid:
		return Red(s)
	case vastv1alpha1.SyncStatusDeleting:
		return Yellow(s)
	default:
		return s
	}
}

// PrimaryStorageClass highlights a primary StorageClass for terminal output.
func PrimaryStorageClass(sc string) string {
	if sc == "" {
		return Yellow("(not set)")
	}
	return Green(sc)
}

// Bool returns a colored string representation of a bool.
func Bool(b bool) string {
	if b {
		return Green("true")
	}
	return "false"
}
