package common

import (
	"regexp"
	"time"
)

const Domain = "vastdata.com"

// CSI parameter prefix for Kubernetes CSI parameters
const CSIParameterPrefix = "csi.storage.k8s.io/"

// Labels
const (
	LabelSubsystem    = Domain + "/subsystem"
	LabelStorageClass = Domain + "/storageClass"
	// LabelManagedBy identifies resources managed by the extensions controller
	// This label can be used to easily search for PVs and PVCs provisioned by this controller
	LabelManagedBy      = "app.kubernetes.io/managed-by"
	LabelManagedByValue = "vast-extensions-controller"

	// Source resource labels (used for efficient filtering via label selectors)
	LabelSourcePVC                             = Domain + "/source-pvc"
	LabelSourcePVCNamespace                    = Domain + "/source-pvc-namespace"
	LabelSourceVolumeReplication               = Domain + "/source-volume-replication"
	LabelSourceVolumeReplicationNamespace      = Domain + "/source-volume-replication-namespace"
	LabelSourceVolumeGroupReplication          = Domain + "/source-volume-group-replication"
	LabelSourceVolumeGroupReplicationNamespace = Domain + "/source-volume-group-replication-namespace"

	// Constellation labels — used to group peer VastReplicationContent objects
	// that belong to the same top-level user-created replication object.

	// LabelSourceVSCR is set on VastReplicationContent objects whose parent
	// VolumeGroupReplication was created by a VastStorageClassReplication.
	// Its value is the VastStorageClassReplication name.  Used to discover
	// peer VRCs that must mirror PVCs across one another.
	LabelSourceVSCR = Domain + "/source-vscr"

	// LabelSourceVVR is set on VastReplicationContent objects whose parent
	// VolumeReplication was created by a VastVolumeReplication.
	// Its value is the VastVolumeReplication name.
	LabelSourceVVR = Domain + "/source-vvr"
)

// StorageClass parameter names
const (
	StorageClassParameterSubsystem   = "subsystem"
	StorageClassParameterVolumeGroup = "volume_group"
	StorageClassParameterRootExport  = "root_export"
	StorageClassParameterQosPolicyId = "qos_policy_id"
)

// Default name format strings for destination PVs and PVCs
const (
	// DefaultPVCNameFormat is the default format string for destination PVC names
	DefaultPVCNameFormat = "{pvc_name}-repl-{endpoint}"

	// DefaultPVNameFormat is the default format string for destination PV names
	DefaultPVNameFormat = "{pv_name}-repl-{endpoint}"
)

// Finalizers
const (
	// FinalizerPVC is used to protect PersistentVolumeClaim resources
	// from deletion until cleanup operations complete
	FinalizerPVC = Domain + "/pvc-protection"

	// FinalizerReplicationContent is used to protect VastReplicationContent CRDs
	// from deletion until all related resources (PVCs, PVs, VAST volumes, snapshots,
	// mirrored VolumeReplication/VolumeGroupReplication objects) have been cleaned up.
	FinalizerReplicationContent = Domain + "/replication-content-protection"

	// AnnotationMirrorSyncRequestedAt is set on secondary VastReplicationContents
	// when the primary gains new PVCs, to trigger immediate mirror PVC/PV sync.
	// The value is an RFC3339 timestamp.
	AnnotationMirrorSyncRequestedAt = Domain + "/mirror-sync-requested-at"

	// AnnotationResyncRequestedAt is set on every VastReplicationContent in the
	// constellation when the user requests a full resync (VSCR spec.resync).
	// The value is an RFC3339 timestamp.
	AnnotationResyncRequestedAt = Domain + "/resync-requested-at"

	// AnnotationCleanupDone is set on a VastReplicationContent after its own
	// CleanVolumes run completes successfully.  The VRC controller waits for ALL
	// constellation peers to carry this annotation before removing the
	// FinalizerReplicationContent finalizer.  This prevents the race where one
	// VRC removes its finalizer (and gets deleted) before a peer's forEachPeer
	// has had a chance to process it.
	AnnotationCleanupDone = Domain + "/cleanup-done"

	// AnnotationSnapshotCleanupWaitDone is set after the one-time pre-cleanup
	// delay that allows in-flight replication snapshots to arrive before listing
	// and deleting them.
	AnnotationSnapshotCleanupWaitDone = Domain + "/snapshot-cleanup-wait-done"

	// FinalizerVSCR is placed on VastStorageClassReplication objects to block
	// deletion until all owned VolumeGroupReplication objects have been removed.
	FinalizerVSCR = Domain + "/vscr-protection"

	// FinalizerVVR is placed on VastVolumeReplication objects to block
	// deletion until all owned VolumeReplication objects have been removed.
	FinalizerVVR = Domain + "/vvr-protection"

)

// csi-addons VolumeReplicationClass / VolumeGroupReplicationClass parameter keys.
// These are the conventional key names recognised by the csi-addons replication sidecar.
const (
	// CSIAddonsParamReplicationSecretName is the parameter key for the Kubernetes
	// secret that holds the replication credentials (VolumeReplicationClass).
	CSIAddonsParamReplicationSecretName = "replication.storage.openshift.io/replication-secret-name"

	// CSIAddonsParamReplicationSecretNamespace is the namespace of the secret
	// referenced by CSIAddonsParamReplicationSecretName.
	CSIAddonsParamReplicationSecretNamespace = "replication.storage.openshift.io/replication-secret-namespace"

	// CSIAddonsParamGroupReplicationSecretName is the parameter key for the
	// secret used by VolumeGroupReplicationClass.
	CSIAddonsParamGroupReplicationSecretName = "replication.storage.openshift.io/group-replication-secret-name"

	// CSIAddonsParamGroupReplicationSecretNamespace is the namespace of the secret
	// referenced by CSIAddonsParamGroupReplicationSecretName.
	CSIAddonsParamGroupReplicationSecretNamespace = "replication.storage.openshift.io/group-replication-secret-namespace"
)

// VAST-specific VolumeReplicationClass / VolumeGroupReplicationClass parameter keys.
// These are passed through by csi-addons as-is to the CSI driver's
// EnableVolumeReplication / EnableVolumeGroupReplication RPC.
const (
	// ReplicationParamStorageClass is the Kubernetes StorageClass name this
	// VolumeReplicationClass / VolumeGroupReplicationClass was created for.
	// Stored as a namespaced parameter so the Python CSI plugin can map a
	// replication class back to its originating StorageClass.
	ReplicationParamStorageClass = Domain + "/storage-class"

	// ReplicationParamSubsystem is the NVMe-oF subsystem name for Block
	// storage classes.  Forwarded from the StorageClass "subsystem" parameter
	// so the Python CSI plugin can look up the subsystem directly without
	// having to derive it from the ppath-source-dir string.
	ReplicationParamSubsystem = Domain + "/subsystem"

	// ReplicationParamPpathName is the name of the single pre-created VAST
	// protected path, set on VRCs / VGRCs for the PRIMARY StorageClass only.
	// The operator creates ONE ppath and attaches additional replication policies
	// as ReplicationStream objects on that same ppath.  The operator waits for
	// the ppath to reach a stable role before writing this parameter; the CSI
	// plugin then looks up the named ppath and skips creation.
	ReplicationParamPpathName = Domain + "/ppath-name"
)

// VMS_SNAPSHOT_DISCOVERY_INTERVAL is the time to wait for VMS to discover in-flight snapshots
// after disabling a protected path. VMS discovers snapshots from EStore via polling every ~15 seconds.
const VMS_SNAPSHOT_DISCOVERY_INTERVAL = 15 * time.Second

// InvalidLabelCharsRegex is the regex pattern for invalid Kubernetes label characters
// Label values must contain only [-_.a-zA-Z0-9]
var InvalidLabelCharsRegex = regexp.MustCompile(`[^a-zA-Z0-9\-_.]`)
