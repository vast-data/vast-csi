package provisioner

import (
	"context"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/vast-data/vast-csi/extensions-controller/internal/common"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/k8s_client"
	"github.com/vast-data/vast-csi/extensions-controller/internal/common/utils"
	corev1 "k8s.io/api/core/v1"
	storagev1 "k8s.io/api/storage/v1"
)

// ---------------------------------------------------------------------------
// Name format interpolation
// ---------------------------------------------------------------------------

// namingValues holds the raw values available for interpolation in name format strings.
// All fields are optional - only the fields relevant to the specific use case need to be set.
type namingValues struct {
	// PVC/PV naming fields
	PVCName string // source PVC name
	PVName  string // source PV name
	// Replication naming fields
	VRName       string // source VolumeReplication name
	VGRName      string // source VolumeGroupReplication name
	VRNamespace  string // source VolumeReplication namespace
	VGRNamespace string // source VolumeGroupReplication namespace
	// Common fields
	Endpoint    string // VAST cluster endpoint from StorageClass secret
	SCName      string // destination StorageClass name
	Provisioner string // StorageClass.Provisioner slugified (dots replaced with dashes)
}

// tokenPattern matches format tokens like {pvc_name}, {pvc_name_suf:30}, {endpoint}, etc.
var tokenPattern = regexp.MustCompile(`\{(\w+?)(?::(\d+))?\}`)

// formatName interpolates a format string using the provided namingValues.
// It supports tokens for both PVC/PV naming and replication CRD naming.
func formatName(format string, vals namingValues) string {
	return tokenPattern.ReplaceAllStringFunc(format, func(match string) string {
		groups := tokenPattern.FindStringSubmatch(match)
		if len(groups) < 2 {
			return match
		}
		token := groups[1]
		limitStr := groups[2] // may be empty

		var limit int
		if limitStr != "" {
			limit, _ = strconv.Atoi(limitStr)
		}

		switch token {
		// PVC/PV naming tokens
		case "pvc_name":
			return vals.PVCName
		case "pvc_name_suf":
			return suffix(vals.PVCName, limit)
		case "pvc_name_pref":
			return prefix(vals.PVCName, limit)
		case "pv_name":
			return vals.PVName
		case "pv_name_suf":
			return suffix(vals.PVName, limit)
		case "pv_name_pref":
			return prefix(vals.PVName, limit)
		// Replication naming tokens
		case "vr_name":
			if limit > 0 {
				return suffix(vals.VRName, limit)
			}
			return vals.VRName
		case "vr_name_suf":
			return suffix(vals.VRName, limit)
		case "vr_name_pref":
			return prefix(vals.VRName, limit)
		case "vgr_name":
			if limit > 0 {
				return suffix(vals.VGRName, limit)
			}
			return vals.VGRName
		case "vgr_name_suf":
			return suffix(vals.VGRName, limit)
		case "vgr_name_pref":
			return prefix(vals.VGRName, limit)
		case "vr_namespace":
			return vals.VRNamespace
		case "vgr_namespace":
			return vals.VGRNamespace
		// Common tokens
		case "endpoint":
			return slugifyEndpoint(vals.Endpoint)
		case "sc_name":
			if limit > 0 {
				return suffix(vals.SCName, limit)
			}
			return vals.SCName
		case "sc_name_suf":
			return suffix(vals.SCName, limit)
		case "sc_name_pref":
			return prefix(vals.SCName, limit)
		case "provisioner":
			return vals.Provisioner
		default:
			return match // leave unknown tokens as-is
		}
	})
}

// suffix returns the last n characters of s. If n <= 0 or n >= len(s), returns s.
func suffix(s string, n int) string {
	if n <= 0 || n >= len(s) {
		return s
	}
	return s[len(s)-n:]
}

// prefix returns the first n characters of s. If n <= 0 or n >= len(s), returns s.
func prefix(s string, n int) string {
	if n <= 0 || n >= len(s) {
		return s
	}
	return s[:n]
}

// slugify converts a string into a DNS-safe label component by replacing dots
// and colons with dashes.
func slugify(s string) string {
	return strings.NewReplacer(".", "-", ":", "-").Replace(s)
}

// slugifyEndpoint converts an endpoint (IP, hostname, or URL) into a DNS-safe
// label component by stripping any scheme and port before slugifying.
func slugifyEndpoint(endpoint string) string {
	if strings.Contains(endpoint, "://") {
		if u, err := url.Parse(endpoint); err == nil {
			endpoint = u.Host
		}
	}
	if host, _, err := net.SplitHostPort(endpoint); err == nil {
		endpoint = host
	}
	return slugify(endpoint)
}

// sanitizeK8sName delegates to the shared utils.SanitizeK8sName.
func sanitizeK8sName(name string) string {
	return utils.SanitizeK8sName(name)
}

// FormatPVCName formats the destination PVC name using the configured format string.
// It derives all necessary values from the provided objects internally.
func FormatPVCName(ctx context.Context, k8sClient *k8s_client.K8sClient, format string, sourcePVC *corev1.PersistentVolumeClaim, sourcePV *corev1.PersistentVolume, destSC *storagev1.StorageClass) (string, error) {
	endpoint, err := endpointFromStorageClass(ctx, k8sClient, destSC)
	if err != nil {
		return "", fmt.Errorf("failed to get endpoint for SC %s: %w", destSC.Name, err)
	}

	vals := namingValues{
		PVCName:  sourcePVC.Name,
		PVName:   sourcePV.Name,
		Endpoint: endpoint,
		SCName:   destSC.Name,
	}
	raw := formatName(format, vals)
	return sanitizeK8sName(raw), nil
}

// FormatPVName formats the destination PV name using the configured format string.
// It derives all necessary values from the provided objects internally.
func FormatPVName(ctx context.Context, k8sClient *k8s_client.K8sClient, format string, sourcePVC *corev1.PersistentVolumeClaim, sourcePV *corev1.PersistentVolume, destSC *storagev1.StorageClass) (string, error) {
	endpoint, err := endpointFromStorageClass(ctx, k8sClient, destSC)
	if err != nil {
		return "", fmt.Errorf("failed to get endpoint for SC %s: %w", destSC.Name, err)
	}

	vals := namingValues{
		PVCName:  sourcePVC.Name,
		PVName:   sourcePV.Name,
		Endpoint: endpoint,
		SCName:   destSC.Name,
	}
	raw := formatName(format, vals)
	return sanitizeK8sName(raw), nil
}

// VSCRReplicationClassFormat and VVRReplicationClassFormat are the fixed format
// strings used to name VolumeReplicationClass / VolumeGroupReplicationClass
// objects.
//
//   - The {provisioner} token expands to the StorageClass provisioner name with
//     dots replaced by dashes (e.g. "csi.vastdata.com" → "csi-vastdata-com",
//     "block.csi.vastdata.com" → "block-csi-vastdata-com").  This guarantees
//     uniqueness regardless of how the CSI driver name is configured in Helm.
//   - The type suffix (vscr/vvr) guarantees that a VSCR and a VVR that both
//     reference the same StorageClass still get distinct classes.
const (
	VSCRReplicationClassFormat = "{sc_name}-{provisioner}-vscr"
	VVRReplicationClassFormat  = "{sc_name}-{provisioner}-vvr"
)

// FormatReplicationClassName formats the replication class name using the configured format string.
// It supports StorageClass name, provisioner slug, and endpoint tokens.
func FormatReplicationClassName(ctx context.Context, k8sClient *k8s_client.K8sClient, format string, sc *storagev1.StorageClass) (string, error) {
	endpoint, err := endpointFromStorageClass(ctx, k8sClient, sc)
	if err != nil {
		return "", fmt.Errorf("failed to get endpoint for SC %s: %w", sc.Name, err)
	}

	vals := namingValues{
		SCName:      sc.Name,
		Endpoint:    endpoint,
		Provisioner: slugify(sc.Provisioner),
	}
	raw := formatName(format, vals)
	return sanitizeK8sName(raw), nil
}

// endpointFromStorageClass extracts the VAST endpoint from the CSI provisioner
// secret referenced in the StorageClass.
func endpointFromStorageClass(ctx context.Context, k8sClient *k8s_client.K8sClient, sc *storagev1.StorageClass) (string, error) {
	// Get CSI-prefixed parameters with prefix stripped
	csiParams := k8sClient.ExtractPrefixedParams(common.CSIParameterPrefix, sc.Parameters)
	secretName := csiParams["provisioner-secret-name"]
	secretNamespace := csiParams["provisioner-secret-namespace"]
	if secretName == "" || secretNamespace == "" {
		return "", fmt.Errorf("StorageClass %s missing provisioner secret parameters", sc.Name)
	}
	return k8sClient.GetSecretValue(ctx, secretName, secretNamespace, "endpoint")
}

func isSourceRole(role string) bool {
	return strings.ToLower(role) == "source"
}

func isDestinationRole(role string) bool {
	return strings.ToLower(role) == "destination"
}

// nfsProtocols returns the NFS protocol list to use for a destination View,
// derived from the StorageClass MountOptions.  Any option of the form
// "vers=4*" or "nfsvers=4*" triggers NFS4; otherwise NFS (v3) is used.
func nfsProtocols(mountOptions []string) []string {
	for _, opt := range mountOptions {
		key, _, value, ok := splitMountOption(opt)
		if ok && (key == "vers" || key == "nfsvers") && strings.HasPrefix(value, "4") {
			return []string{"NFS4"}
		}
	}
	return []string{"NFS"}
}

// splitMountOption parses a single mount option string of the form "key=value"
// or bare "key".  Returns (key, "=", value, true) when an "=" is present, and
// (opt, "", "", false) for bare flags.
func splitMountOption(opt string) (key, sep, value string, hasValue bool) {
	if idx := strings.IndexByte(opt, '='); idx >= 0 {
		return strings.TrimSpace(opt[:idx]), "=", strings.TrimSpace(opt[idx+1:]), true
	}
	return strings.TrimSpace(opt), "", "", false
}
