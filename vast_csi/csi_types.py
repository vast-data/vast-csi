from __future__ import absolute_import

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from google.protobuf import wrappers_pb2 as wrappers

from .proto import csi_pb2
from .proto import cosi_pb2
from .proto import replication_pb2
from .proto import volumegroup_pb2


class EnumWrapper(object):
    def __init__(self, enum):
        self._enum = enum

    def __getattr__(self, name):
        try:
            return getattr(self._enum, name)
        except AttributeError:
            return self._enum.Value(name)


Bool = wrappers.BoolValue

InfoResp = csi_pb2.GetPluginInfoResponse
NodeInfoResp = csi_pb2.NodeGetInfoResponse

Capability = csi_pb2.PluginCapability
Service = Capability.Service
ServiceType = EnumWrapper(Service.Type)
Expansion = Capability.VolumeExpansion
ExpansionType = EnumWrapper(Expansion.Type)
CtrlCapability = csi_pb2.ControllerServiceCapability
CtrlCapabilityType = EnumWrapper(CtrlCapability.RPC.Type)
CtrlCapabilityResp = csi_pb2.ControllerGetCapabilitiesResponse

NodeCapability = csi_pb2.NodeServiceCapability
NodeCapabilityType = EnumWrapper(NodeCapability.RPC.Type)
NodeCapabilityResp = csi_pb2.NodeGetCapabilitiesResponse

ListResp = csi_pb2.ListVolumesResponse
ValidateResp = csi_pb2.ValidateVolumeCapabilitiesResponse

CtrlPublishResp = csi_pb2.ControllerPublishVolumeResponse
CtrlUnpublishResp = csi_pb2.ControllerUnpublishVolumeResponse
CtrlExpandResp = csi_pb2.ControllerExpandVolumeResponse

CapabilitiesResp = csi_pb2.GetPluginCapabilitiesResponse

VolumeCapability = csi_pb2.VolumeCapability
MountVolume = VolumeCapability.MountVolume
BlockVolume = VolumeCapability.BlockVolume
AccessMode = VolumeCapability.AccessMode
AccessModeType = EnumWrapper(AccessMode.Mode)

StageResp = csi_pb2.NodeStageVolumeResponse
UnstageResp = csi_pb2.NodeUnstageVolumeResponse
NodePublishResp = csi_pb2.NodePublishVolumeResponse
NodeUnpublishResp = csi_pb2.NodeUnpublishVolumeResponse
NodeExpandResp = csi_pb2.NodeExpandVolumeResponse
ProbeRespOK = csi_pb2.ProbeResponse(ready=Bool(value=True))
ProbeRespNotReady = csi_pb2.ProbeResponse(ready=Bool(value=False))
CapacityResp = csi_pb2.GetCapacityResponse
CreateResp = csi_pb2.CreateVolumeResponse
DeleteResp = csi_pb2.DeleteVolumeResponse
Volume = csi_pb2.Volume

VolumeContentSource = csi_pb2.VolumeContentSource
VolumeSource = csi_pb2.VolumeContentSource.VolumeSource
SnapshotSource = csi_pb2.VolumeContentSource.SnapshotSource

Snapshot = csi_pb2.Snapshot
CreateSnapResp = csi_pb2.CreateSnapshotResponse
DeleteSnapResp = csi_pb2.DeleteSnapshotResponse
ListSnapResp = csi_pb2.ListSnapshotsResponse
SnapEntry = ListSnapResp.Entry

VolumeStatsResp = csi_pb2.NodeGetVolumeStatsResponse
VolumeUsage = csi_pb2.VolumeUsage
UsageUnit = EnumWrapper(VolumeUsage.Unit)

Topology = csi_pb2.Topology

# COSI types
DriverGetInfoResp = cosi_pb2.DriverGetInfoResponse
DriverCreateBucketResp = cosi_pb2.DriverCreateBucketResponse
DriverGrantBucketAccessResp = cosi_pb2.DriverGrantBucketAccessResponse
DriverRevokeBucketAccessResp = cosi_pb2.DriverRevokeBucketAccessResponse
DriverDeleteBucketResp = cosi_pb2.DriverDeleteBucketResponse
Protocol = cosi_pb2.Protocol
S3 = cosi_pb2.S3
S3SignatureVersion = cosi_pb2.S3SignatureVersion
CredentialDetails = cosi_pb2.CredentialDetails

# CSI-Addons Replication types
EnableVolumeReplicationResp = replication_pb2.EnableVolumeReplicationResponse
DisableVolumeReplicationResp = replication_pb2.DisableVolumeReplicationResponse
PromoteVolumeResp = replication_pb2.PromoteVolumeResponse
DemoteVolumeResp = replication_pb2.DemoteVolumeResponse
ResyncVolumeResp = replication_pb2.ResyncVolumeResponse
GetVolumeReplicationInfoResp = replication_pb2.GetVolumeReplicationInfoResponse
ReplicationSource = replication_pb2.ReplicationSource
ReplicationVolumeSource = replication_pb2.ReplicationSource.VolumeSource
ReplicationVolumeGroupSource = replication_pb2.ReplicationSource.VolumeGroupSource
ReplicationStatus = EnumWrapper(replication_pb2.GetVolumeReplicationInfoResponse.Status)

# CSI-Addons VolumeGroup types
CreateVolumeGroupResp = volumegroup_pb2.CreateVolumeGroupResponse
DeleteVolumeGroupResp = volumegroup_pb2.DeleteVolumeGroupResponse
ModifyVolumeGroupMembershipResp = volumegroup_pb2.ModifyVolumeGroupMembershipResponse
ControllerGetVolumeGroupResp = volumegroup_pb2.ControllerGetVolumeGroupResponse
ListVolumeGroupsResp = volumegroup_pb2.ListVolumeGroupsResponse
VolumeGroup = volumegroup_pb2.VolumeGroup
VolumeGroupVolume = csi_pb2.Volume  # Volume entry within a VolumeGroup (uses CSI Volume definition)

# gRPC statuses
FAILED_PRECONDITION = grpc.StatusCode.FAILED_PRECONDITION
INVALID_ARGUMENT = grpc.StatusCode.INVALID_ARGUMENT
ALREADY_EXISTS = grpc.StatusCode.ALREADY_EXISTS
NOT_FOUND = grpc.StatusCode.NOT_FOUND
ABORTED = grpc.StatusCode.ABORTED
UNKNOWN = grpc.StatusCode.UNKNOWN
OUT_OF_RANGE = grpc.StatusCode.OUT_OF_RANGE
RESOURCE_EXHAUSTED = grpc.StatusCode.RESOURCE_EXHAUSTED
UNAVAILABLE = grpc.StatusCode.UNAVAILABLE
INTERNAL = grpc.StatusCode.INTERNAL
