package events

// Event reasons for ReplicationProvision lifecycle events.
const (
	// ReasonProvisionSucceeded is emitted when all mirrored resources for a
	// destination StorageClass have been created successfully.
	ReasonProvisionSucceeded = "ProvisionSucceeded"

	// ReasonProvisionFailed is emitted when the provisioner returns an error
	// during resource creation.
	ReasonProvisionFailed = "ProvisionFailed"

	// ReasonProvisionSkipped is emitted when provisioning is deferred because
	// a required resource (e.g. source PVC) is not yet available.
	ReasonProvisionSkipped = "ProvisionSkipped"

	// ReasonCleanupSucceeded is emitted when all managed resources for a
	// destination StorageClass have been deleted successfully.
	ReasonCleanupSucceeded = "CleanupSucceeded"

	// ReasonCleanupFailed is emitted when the provisioner returns an error
	// during resource deletion.
	ReasonCleanupFailed = "CleanupFailed"

	// ReasonMirroredObjectPending is emitted when the mirrored VolumeReplication
	// or VolumeGroupReplication has not yet appeared; metadata will be recorded
	// on the next reconcile.
	ReasonMirroredObjectPending = "MirroredObjectPending"

	// ReasonStatusUpdateFailed is emitted when updating the ReplicationProvision
	// status sub-resource fails.
	ReasonStatusUpdateFailed = "StatusUpdateFailed"

	// ReasonConfigInvalid is emitted when a controller configuration combination
	// is invalid (e.g. CRD creation enabled without PVC/PV creation).
	ReasonConfigInvalid = "ConfigInvalid"

	// --- provisioner milestones ---

	// ReasonPVCPVCreated is emitted when a destination PV+PVC pair has been
	// created for a given source PVC.
	ReasonPVCPVCreated = "PVCPVCreated"

	// ReasonPVCPVPairsComplete is emitted when all destination PV+PVC pairs
	// for a VolumeGroupReplication have been created.
	ReasonPVCPVPairsComplete = "PVCPVPairsComplete"

	// ReasonVolumesEnsured is emitted when all VAST volumes for a
	// VolumeGroupReplication have been created or verified.
	ReasonVolumesEnsured = "VolumesEnsured"

	// ReasonViewCreated is emitted when a new VAST NFS View has been created
	// on a peer cluster during file provisioning.
	ReasonViewCreated = "ViewCreated"

	// ReasonQuotaCreated is emitted when a new VAST Quota has been created
	// on a peer cluster during file provisioning.
	ReasonQuotaCreated = "QuotaCreated"

	// ReasonReplicationClassEnsured is emitted when a VolumeReplicationClass
	// or VolumeGroupReplicationClass has been created or verified.
	ReasonReplicationClassEnsured = "ReplicationClassEnsured"

	// ReasonVolumeReplicationCreated is emitted when a destination
	// VolumeReplication CRD has been created.
	ReasonVolumeReplicationCreated = "VolumeReplicationCreated"

	// ReasonVolumeGroupReplicationCreated is emitted when a destination
	// VolumeGroupReplication CRD has been created.
	ReasonVolumeGroupReplicationCreated = "VolumeGroupReplicationCreated"

	// ReasonVolumeReplicationUpdated is emitted when an existing
	// VolumeReplication's replicationState is patched (e.g. after a
	// primary StorageClass switch).
	ReasonVolumeReplicationUpdated = "VolumeReplicationUpdated"

	// ReasonVolumeGroupReplicationUpdated is emitted when an existing
	// VolumeGroupReplication's replicationState is patched (e.g. after a
	// primary StorageClass switch).
	ReasonVolumeGroupReplicationUpdated = "VolumeGroupReplicationUpdated"

	// ReasonVRCCreated is emitted when a new VastReplicationContent object
	// is created for a VolumeReplication or VolumeGroupReplication.
	ReasonVRCCreated = "VRCCreated"

	// ReasonVRCUpdated is emitted when one or more fields of an existing
	// VastReplicationContent spec are patched (PVCs, ReplicationState, ppath fields).
	ReasonVRCUpdated = "VRCUpdated"

	// ReasonPpathNotReady is emitted when the VAST protected path has not yet
	// reached an active state; the controller will requeue and retry.
	ReasonPpathNotReady = "PpathNotReady"

	// ReasonReconcileFailed is emitted when the reconcile loop encounters a
	// hard (non-transient) error, such as a missing VAST view or a failed
	// protection policy.  The controller will keep retrying with backoff.
	ReasonReconcileFailed = "ReconcileFailed"

	// ReasonPpathDisabled is emitted when the protected path is disabled as the
	// first step of VSCR/VVR deletion, before any VAST objects are removed.
	ReasonPpathDisabled = "PpathDisabled"

	// ReasonPpathDeleted is emitted when the protected path has been
	// successfully deleted from the VAST cluster during cleanup.
	ReasonPpathDeleted = "PpathDeleted"

	// ReasonCleanupStarted is emitted when the provisioner begins deleting
	// managed resources for a VolumeReplication or VolumeGroupReplication.
	ReasonCleanupStarted = "CleanupStarted"

	// ReasonVolumeReplicationDeleted is emitted when a destination
	// VolumeReplication CRD is being deleted during cleanup.
	ReasonVolumeReplicationDeleted = "VolumeReplicationDeleted"

	// ReasonVolumeGroupReplicationDeleted is emitted when a destination
	// VolumeGroupReplication CRD is being deleted during cleanup.
	ReasonVolumeGroupReplicationDeleted = "VolumeGroupReplicationDeleted"

	// ReasonSnapshotsDeleted is emitted after all replication snapshots for a
	// path have been deleted.
	ReasonSnapshotsDeleted = "SnapshotsDeleted"

	// ReasonVASTVolumeDeleted is emitted when a VAST volume has been deleted.
	ReasonVASTVolumeDeleted = "VASTVolumeDeleted"

	// ReasonPVCDeleted is emitted when a destination PVC has been deleted.
	ReasonPVCDeleted = "PVCDeleted"

	// ReasonPVDeleted is emitted when a destination PV has been deleted.
	ReasonPVDeleted = "PVDeleted"

	// ReasonPrimaryStorageClassChanged is emitted when spec.primaryStorageClass
	// is changed and Status.CurrentPrimaryStorageClass is updated to reflect it.
	ReasonPrimaryStorageClassChanged = "PrimaryStorageClassChanged"

	// ReasonActionChanged is emitted when spec.action is set or changed and
	// Status.LastAction is updated to reflect the new requested operation.
	ReasonActionChanged = "ActionChanged"
)
