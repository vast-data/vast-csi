# Copyright 2025 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
VAST CSI-Addons Volume Replication Plugin

Implements CSI-Addons Volume Replication for NFS and Block (NVMe-oF) volumes.
Follows the CSI-Addons replication specification.
"""
import os
from abc import abstractmethod
from enum import StrEnum
from datetime import datetime, timezone

import requests.exceptions
import urllib3.exceptions
from google.protobuf import timestamp_pb2, duration_pb2

from easypy.caching import cached_property

from vast_csi.proto import replication_pb2_grpc
from vast_csi.logging import logger
from vast_csi.plugins.base import Instrumented, AddonsIdentity
from vast_csi.exceptions import Abort, WaitResourceFailed, ApiError
from vast_csi import csi_types as types
from vast_csi.utils import to_abort, parse_duration_to_timestamp
from vast_csi.filesystem_utils import resource_locked
from vast_csi.extensions_client import get_failover_type_if_available

from vast_csi.plugins.volumegroup import (
    _parse_volume_group_id,
    ID_SUFFIX_LENGTH,
    REPLICATION_PARAM_PPATH_NAME,
    REPLICATION_PARAM_STORAGE_CLASS,
)

CONF = None
CLUSTER_UNREACHABLE_ERR_SET = (
    requests.exceptions.ConnectionError,
    urllib3.exceptions.MaxRetryError,
    urllib3.exceptions.ReadTimeoutError,
    urllib3.exceptions.TimeoutError,
)


class ReplicationRole(StrEnum):
    """
    Replication role for protected paths.

    Matches VAST Control::ReplicationGroupRoleState enum.
    """

    SOURCE = "SOURCE"
    DESTINATION = "DESTINATION"
    STANDALONE = "STANDALONE"
    INVALID = "INVALID"
    NA = "N/A"

    # Transitional states
    BECOMING_SOURCE = "BECOMING_SOURCE"
    BECOMING_STANDALONE = "BECOMING_STANDALONE"
    BECOMING_DESTINATION = "BECOMING_DESTINATION"
    GRACEFULLY_BECOMING_DESTINATION = "GRACEFULLY_BECOMING_DESTINATION"
    GRACEFULLY_BECOMING_SOURCE = "GRACEFULLY_BECOMING_SOURCE"
    BECOMING_SOURCE_ASK_FOR_SOURCE = "BECOMING_SOURCE_ASK_FOR_SOURCE"
    BECOMING_SOURCE_ATTACHING_MEMBERS = "BECOMING_SOURCE_ATTACHING_MEMBERS"
    BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS = "BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS"
    BECOMING_SOURCE_GRACEFULLY_FAILING_OVER = "BECOMING_SOURCE_GRACEFULLY_FAILING_OVER"

    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, value: str) -> "ReplicationRole":
        """Parse ReplicationRole from a string, returning UNKNOWN for unrecognised values."""
        if not value:
            return cls.UNKNOWN
        if value.upper() == "N/A":
            return cls.NA
        try:
            return cls[value.upper().replace(" ", "_")]
        except KeyError:
            logger.warning(f"Unknown replication role: {value!r}")
            return cls.UNKNOWN

    def is_source(self) -> bool:
        return self == ReplicationRole.SOURCE

    def is_destination(self) -> bool:
        return self == ReplicationRole.DESTINATION

    def is_transitional(self) -> bool:
        return self.value.startswith("BECOMING_")

    def is_standalone(self) -> bool:
        return self == ReplicationRole.STANDALONE

    def is_stable(self) -> bool:
        return self in (
            ReplicationRole.SOURCE,
            ReplicationRole.DESTINATION,
            ReplicationRole.STANDALONE,
        )


class ReplicationAction(StrEnum):
    """Replication failover action requested by the StorageClass annotation."""

    UNGRACEFUL = "ungraceful"
    GRACEFUL = "graceful"


def _parse_policy_timestamps(ppolicy):
    """Extract keep-local / keep-remote expiry timestamps from a protection policy."""
    first_frame = ppolicy.frames[0] if ppolicy.frames else {}
    keep_local = first_frame.get("keep-local", "1H")
    keep_remote = first_frame.get("keep-remote", "1H")
    try:
        time_expires_local = parse_duration_to_timestamp(keep_local)
        time_expires_target = parse_duration_to_timestamp(keep_remote)
        logger.info(
            f"Parsed protection policy timestamps: "
            f"keep-local: {keep_local} -> {time_expires_local}, "
            f"keep-remote: {keep_remote} -> {time_expires_target}"
        )
    except ValueError as e:
        logger.warning(f"Failed to parse duration from protection policy: {e}. Using defaults.")
        time_expires_local = parse_duration_to_timestamp("1H")
        time_expires_target = parse_duration_to_timestamp("1H")
    return time_expires_local, time_expires_target


class ReplicationSource:
    """
    Wrapper for CSI-Addons replication source protobuf.

    Provides convenient properties to check source type and get volume IDs.
    """

    def __init__(self, replication_source, vms_session, controller):
        """
        Initialize ReplicationSource.

        Args:
            replication_source: CSI-Addons ReplicationSource protobuf
            vms_session: VAST VMS session. Required for volume group sources to query member volumes.
            controller: BaseReplicationController that provides type-specific volume operations
        """
        if not replication_source:
            raise Abort(types.INVALID_ARGUMENT, "replication_source must be specified")

        self._source = replication_source
        self._vms_session = vms_session
        self._controller = controller

        # Validate that either volume or volumegroup is specified
        if not (
            replication_source.HasField("volume")
            or replication_source.HasField("volumegroup")
        ):
            raise Abort(
                types.INVALID_ARGUMENT,
                "replication_source must specify either volume or volumegroup",
            )

    @cached_property
    def is_volume(self):
        """Check if this is a single volume source."""
        return self._source.HasField("volume")

    @cached_property
    def is_volume_group(self):
        """Check if this is a volume group source."""
        return self._source.HasField("volumegroup")

    @cached_property
    def volume_id(self):
        """Get the single volume ID (if this is a volume source)."""
        if not self.is_volume:
            raise Abort(
                types.INVALID_ARGUMENT,
                "Cannot get volume_id from volume group source.",
            )
        return os.path.basename(self._source.volume.volume_id)

    @cached_property
    def volume_group_id(self):
        """Get the volume group ID prefix (if this is a volumegroup source).

        Returns only the suffix part of the encoded ID (before '@').
        For example, from "vg-9dc74656c@t=default:p=/k8s" returns "vg-9dc74656c".
        """
        if not self.is_volume_group:
            raise Abort(
                types.INVALID_ARGUMENT,
                "Cannot get volume_group_id from single volume source.",
            )
        return self.parsed.suffix

    @cached_property
    def identifier(self):
        if self.is_volume:
            return self.volume_id[-ID_SUFFIX_LENGTH:]
        else:
            return self.volume_group_id

    @cached_property
    def parsed(self):
        volume_group_id = self._source.volumegroup.volume_group_id
        return _parse_volume_group_id(volume_group_id)

    @cached_property
    def volumes_in_group(self):
        """Get all volumes in this volume group (views for NFS, volumes for Block)."""
        return self._controller._list_volumes_in_group(self._vms_session, self.parsed)

    @cached_property
    def volumes_mapping(self):
        """Get a dict mapping volume IDs to volume objects."""
        return {
            self._controller._get_volume_id(vol): vol for vol in self.volumes_in_group
        }

    @cached_property
    def volume_ids(self):
        """
        Get a list of volume IDs to process.

        For single volume sources, returns a list with one volume ID.
        For volume group sources, delegates to the controller to list and
        extract volume IDs from the group members.
        """
        if self.is_volume:
            # Use the normalized volume_id property which strips leading slashes
            return [self.volume_id]
        else:
            volume_group_id = self._source.volumegroup.volume_group_id
            logger.debug(f"Fetching volume group {volume_group_id} member volume IDs")
            ids = sorted(self.volumes_mapping.keys())
            if not ids:
                raise Abort(
                    types.ABORTED,
                    f"VolumeGroup {volume_group_id} has no member volumes yet; "
                    f"waiting for first PVC to be added",
                )
            return ids

    def __str__(self):
        if self.is_volume:
            return f"Volume({self.volume_id})"
        else:
            return f"VolumeGroup({self.volume_group_id})"

    __repr__ = __str__


################################################################
#
# Base Replication Controller
#
################################################################


class BaseReplicationController(replication_pb2_grpc.ControllerServicer):
    """
    Base class for CSI-Addons Volume Replication Controllers.
    """

    # Subclasses set this to "NFS" or "BLOCK" for log messages.
    volume_type: str = ""

    def __init__(self, config):
        self.config = config

    def _make_repl_source(self, replication_source, vms_session):
        """Create a ReplicationSource bound to this controller."""
        return ReplicationSource(replication_source, vms_session, controller=self)

    @abstractmethod
    def _list_volumes_in_group(self, vms_session, parsed):
        """List all volumes belonging to a volume group."""

    @abstractmethod
    def _get_volume_id(self, volume):
        """Extract a volume ID (short name) from a volume object."""

    @classmethod
    def _make_parameters(cls, parameters):
        """Convert parameters to a dict."""
        return dict(parameters) if parameters else {}

    @classmethod
    def _get_ppath_name(cls, params: dict) -> str:
        """Extract the protected path name from VRC parameters."""
        ppath_name = params.get(REPLICATION_PARAM_PPATH_NAME)
        if not ppath_name:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"Missing required VolumeReplicationClass parameter "
                f"{REPLICATION_PARAM_PPATH_NAME!r}",
            )
        return ppath_name

    _PPATH_READY_STATES = {"active", "partially active"}

    @classmethod
    def _validate_active_ppath_status(cls, ppath):
        """Raise Abort if the protected path is not in a ready state.

        Both "active" and "partially active" are considered ready.
        "Partially Active" is the normal steady state for group-replication
        """
        current_state = (ppath.get("protected_path_state") or "").lower()
        if current_state not in cls._PPATH_READY_STATES:
            failure_reason = ppath.get("failure_reason")
            error_msg = (
                f"Protected path {ppath.name!r} is not in a ready state: {current_state}"
            )
            if failure_reason:
                error_msg += f" ({failure_reason})"
            raise Abort(types.ABORTED, error_msg)
        return current_state

    @classmethod
    def _wait_for_ppath_active(cls, ppath, vms_session):
        """Block until the protected path reaches active state."""
        try:
            cls._validate_active_ppath_status(ppath)
        except Abort as e:
            logger.info(f"{cls.volume_type}: {e}")
            vms_session.protectedpaths.wait_active(ppath.id)

    @classmethod
    def _get_failover_type(cls, params) -> ReplicationAction:
        action = ReplicationAction.UNGRACEFUL
        if storage_class := params.get(REPLICATION_PARAM_STORAGE_CLASS):
            if raw := get_failover_type_if_available(storage_class):
                action = ReplicationAction(raw)

        return action

    # ------------------------------------------------------------------
    # EnableVolumeReplication
    # ------------------------------------------------------------------

    def EnableVolumeReplication(
        self,
        vms_session,
        exit_stack,
        parameters,
        replication_source,
    ):
        """
        Enable replication for an existing protected path.

        The ppath was already created by the extensions-controller operator.
        This method only waits for it to reach active state and sets enabled=True.
        """
        params = self._make_parameters(parameters)
        ppath_name = self._get_ppath_name(params)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(
            f"{self.volume_type}: Enabling replication for "
            f"protected path {ppath_name!r} on {vms_session!r}"
        )
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        ppath = vms_session.protectedpaths.wait(name=ppath_name)

        with locked.with_message(
            f"Waiting for protected path {ppath_name!r} to reach active state"
        ):
            self._wait_for_ppath_active(ppath=ppath, vms_session=vms_session)

        if vms_session.protectedpaths.ensure_set_enabled(ppath, True):
            logger.info(
                f"{self.volume_type}: Replication enabled for "
                f"protected path {ppath_name!r} on {vms_session!r}"
            )
        else:
            logger.info(
                f"{self.volume_type}: Replication already enabled for "
                f"{ppath_name!r}. No action taken."
            )

        return types.EnableVolumeReplicationResp()

    # ------------------------------------------------------------------
    # DisableVolumeReplication
    # ------------------------------------------------------------------

    def DisableVolumeReplication(
        self,
        vms_session,
        exit_stack,
        parameters,
        replication_source,
    ):
        """Disable replication for a volume or volume group."""
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)
        ppath_name = self._get_ppath_name(params)

        logger.info(
            f"{self.volume_type}: Disabling replication for "
            f"protected path {ppath_name!r}"
        )

        exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )
        try:
            ppath = vms_session.protectedpaths.wait(name=ppath_name)
        except WaitResourceFailed:
            logger.info(
                f"{self.volume_type}: Protected path {ppath_name!r} not found. No action taken."
            )
            return types.DisableVolumeReplicationResp()
        except CLUSTER_UNREACHABLE_ERR_SET as exc:
            logger.warning(
                f"{self.volume_type}: Could not reach VMS while fetching protected path "
                f"{ppath_name!r} to disable replication "
                f"({type(exc).__name__}: {exc}). Treating as no-op."
            )
            return types.DisableVolumeReplicationResp()
        except ApiError as exc:
            if exc.response.status_code is None:
                logger.warning(
                    f"{self.volume_type}: Could not reach VMS while fetching protected path "
                    f"({type(exc).__name__}: {exc}). Treating as no-op."
                )
                return types.DisableVolumeReplicationResp()
            raise

        if vms_session.protectedpaths.ensure_set_enabled(ppath, False):
            logger.info(
                f"{self.volume_type}: Replication disabled for "
                f"protected path {ppath_name!r} on {vms_session!r}"
            )

        return types.DisableVolumeReplicationResp()

    # ------------------------------------------------------------------
    # PromoteVolume
    # ------------------------------------------------------------------

    def PromoteVolume(
        self,
        vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """
        Promote the local cluster to primary (SOURCE).

        The failover mode (graceful vs ungraceful) is driven by the
        ``replication.vastdata.com/action`` annotation on the StorageClass,
        resolved via :meth:`_get_failover_type`.  Graceful failover
        coordinates with the remote cluster to drain in-flight I/O before
        switching roles; ungraceful switches immediately.

        For graceful failover the method raises ``ABORTED`` when the role has
        not yet settled
        allowing the CSI controller to retry until the transition completes.

        For ungraceful failover the flow spans two retry rounds:

        1. ``DESTINATION`` → :meth:`failover(graceful=False)` → both sides
           land on ``STANDALONE`` → raises ``ABORTED`` to trigger retry.
        2. ``STANDALONE`` → :meth:`force_failover` → promotes this side to
           ``SOURCE`` → returns successfully.
        """
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)
        ppath_name = self._get_ppath_name(params)

        logger.info(
            f"{self.volume_type}: Promoting {repl_source} to primary on local cluster, "
            f"protected path: {ppath_name!r}"
        )
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        action = self._get_failover_type(params)
        graceful = action == ReplicationAction.GRACEFUL
        ppath = vms_session.protectedpaths.wait(name=ppath_name)
        with locked.with_message(
            f"Waiting for protected path {ppath_name!r} to reach active state"
        ):
            self._wait_for_ppath_active(ppath=ppath, vms_session=vms_session)

        current_role = ReplicationRole.from_string(ppath.get("role"))
        logger.info(
            f"{self.volume_type}: {vms_session!r} - "
            f"protected path {ppath_name!r}, current role: {current_role.value!r}"
        )

        if current_role.is_destination():
            with locked.with_message(
                f"{action.value} failover(promotion) for {repl_source} is not yet completed. Waiting..."
            ), to_abort():
                vms_session.protectedpaths.failover(
                    protected_path_id=ppath.id,
                    graceful=graceful,
                )

        if not graceful and current_role.is_standalone():
            # Ungraceful failover leaves both sides as STANDALONE.  A subsequent
            # force_failover is required to promote this side to SOURCE.
            logger.info(
                f"{self.volume_type}: {vms_session!r} - "
                f"protected path {ppath_name!r} is STANDALONE after ungraceful failover, "
                f"promoting to SOURCE via force_failover"
            )
            with locked.with_message(
                f"force_failover for {repl_source}: promoting STANDALONE to SOURCE..."
            ), to_abort():
                vms_session.protectedpaths.force_failover(protected_path_id=ppath.id)

        if not current_role.is_source():
            raise Abort(
                types.ABORTED,
                f"{vms_session} - protected path {ppath_name!r} "
                f"is not yet completed failover transition. "
                f"Current role: {current_role.value!r}  "
                f"Expected: {ReplicationRole.SOURCE.value!r}",
            )

        # Finally, make sure replication is enabled on SOURCE cluster
        if vms_session.protectedpaths.ensure_set_enabled(ppath, True):
            logger.info(
                f"{self.volume_type}: Replication enabled for "
                f"protected path {ppath_name!r} on SOURCE {vms_session!r}"
            )

        return types.PromoteVolumeResp()

    # ------------------------------------------------------------------
    # DemoteVolume
    # ------------------------------------------------------------------

    def DemoteVolume(
        self,
        vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """
        Demote the local cluster to secondary (DESTINATION).
        """
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)
        ppath_name = self._get_ppath_name(params)

        logger.info(
            f"{self.volume_type}: Demoting {repl_source} to secondary, "
            f"protected path: {ppath_name!r}"
        )
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        try:
            ppath = vms_session.protectedpaths.wait(name=ppath_name)
        except CLUSTER_UNREACHABLE_ERR_SET as exc:
            logger.warning(
                f"{self.volume_type}: Could not reach VMS while fetching protected path "
                f"({type(exc).__name__}: {exc}). Treating as no-op."
            )
            return types.DemoteVolumeResp()
        except ApiError as exc:
            if exc.response.status_code is None:
                logger.warning(
                    f"{self.volume_type}: Could not reach VMS while fetching protected path "
                    f"({type(exc).__name__}: {exc}). Treating as no-op."
                )
                return types.DemoteVolumeResp()
            raise


        with locked.with_message(
            f"Waiting for protected path {ppath_name!r} to reach active state"
        ):
            self._wait_for_ppath_active(ppath=ppath, vms_session=vms_session)

        if vms_session.protectedpaths.ensure_set_enabled(ppath, True):
            logger.info(
                f"{self.volume_type}: Replication enabled for "
                f"protected path {ppath_name!r} on {vms_session!r}"
            )

        return types.DemoteVolumeResp()

    # ------------------------------------------------------------------
    # ResyncVolume
    # ------------------------------------------------------------------

    def ResyncVolume(
        self,
        vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """Trigger immediate replication from the local SOURCE cluster."""
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)
        ppath_name = self._get_ppath_name(params)

        logger.info(f"{self.volume_type}: Resyncing {repl_source}, protected path: {ppath_name!r}")
        exit_stack.enter_context(resource_locked(repl_source.identifier, abort_on_error=True))

        ppath = vms_session.protectedpaths.wait(name=ppath_name)

        current_role = ReplicationRole.from_string(ppath.get("role"))
        if not current_role.is_source():
            logger.info(
                f"{self.volume_type}: Local cluster {vms_session!r} is not SOURCE "
                f"(role: {current_role.value!r}). Resync is a no-op on non-SOURCE clusters."
            )
            return types.ResyncVolumeResp(ready=True)

        logger.info(
            f"{self.volume_type}: Triggering resync from local cluster {vms_session!r}, "
            f"protected path: {ppath_name!r}"
        )

        ppolicy = vms_session.protectionpolicies.get(ppath.protection_policy_id)
        if not ppolicy:
            raise Abort(
                types.NOT_FOUND,
                f"Protection policy {ppath.protection_policy_id} not found",
            )

        time_expires_local, time_expires_target = _parse_policy_timestamps(ppolicy)
        vms_session.protectedpaths.replicate_now(
            protected_path_id=ppath.id,
            time_expires_local=time_expires_local,
            time_expires_target=time_expires_target,
        )
        logger.info(
            f"{self.volume_type}: Resync triggered for protected path {ppath_name!r}"
        )

        state = (ppath.get("protected_path_state") or "").lower()
        return types.ResyncVolumeResp(ready=(state == "active"))

    # ------------------------------------------------------------------
    # GetVolumeReplicationInfo
    # ------------------------------------------------------------------

    def GetVolumeReplicationInfo(
        self,
        vms_session,
        exit_stack,
        replication_source,
    ):
        """Get replication status for a volume from the local cluster."""
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.debug(f"{self.volume_type}: Getting replication info for {repl_source}")

        if repl_source.parsed.ppath_name:
            ppath_name = repl_source.parsed.ppath_name
            logger.debug(f"{self.volume_type}: Using embedded ppath name {ppath_name!r}")
            lookup_kwargs = {"name": ppath_name}
        else:
            return types.GetVolumeReplicationInfoResp(
                last_sync_time=timestamp_pb2.Timestamp(),
                last_sync_duration=None,
                last_sync_bytes=0,
                status=types.ReplicationStatus.HEALTHY,
                status_message=f"{repl_source}: No protected path name specified",
            )

        try:
            ppath = vms_session.protectedpaths.one(fail_if_missing=True, **lookup_kwargs)
        except Exception as exc:
            logger.warning(
                f"{self.volume_type}: Protected path not found on local cluster "
                f"{vms_session!r}: {exc}",
            )
            return types.GetVolumeReplicationInfoResp(
                last_sync_time=timestamp_pb2.Timestamp(),
                last_sync_duration=None,
                last_sync_bytes=0,
                status=types.ReplicationStatus.DEGRADED,
                status_message=f"{repl_source}: Protected path not found on local cluster: {exc}",
            )

        current_role = ReplicationRole.from_string(ppath.get("role"))
        logger.info(
            f"{self.volume_type}: Local cluster {vms_session!r} role: {current_role.value!r}"
        )

        last_restore_point_creation_time = ppath.get("last_restore_point_creation_time")
        last_restore_point_time = ppath.get("last_restore_point_time")

        # Initialize response fields
        last_sync_time = timestamp_pb2.Timestamp()
        last_sync_duration = None
        last_sync_bytes = 0

        if last_restore_point_creation_time and last_restore_point_time:
            start_str = last_restore_point_creation_time.replace("Z", "+00:00")
            end_str = last_restore_point_time.replace("Z", "+00:00")
            if "." in start_str:
                start_time = datetime.fromisoformat(start_str)
            else:
                start_time = datetime.strptime(
                    start_str.split("+")[0], "%Y-%m-%dT%H:%M:%S"
                )
                start_time = start_time.replace(tzinfo=timezone.utc)

            if "." in end_str:
                end_time = datetime.fromisoformat(end_str)
            else:
                end_time = datetime.strptime(end_str.split("+")[0], "%Y-%m-%dT%H:%M:%S")
                end_time = end_time.replace(tzinfo=timezone.utc)

            last_sync_time.FromDatetime(start_time)
            duration_seconds = int((end_time - start_time).total_seconds())
            last_sync_duration = duration_pb2.Duration(seconds=duration_seconds)

        protected_path_state = (ppath.get("protected_path_state") or "").lower()
        health = (ppath.get("health") or "").upper()

        if not last_restore_point_creation_time:
            status = types.ReplicationStatus.UNKNOWN
            status_message = f"{repl_source}: Initial sync not yet completed"
        elif health != "OK":
            status = types.ReplicationStatus.ERROR
            status_message = (
                f"{repl_source}: Protected path health: {health}, "
                f"failure: {ppath.get('failure_reason', 'unknown')}"
            )
        elif protected_path_state == "active" and health == "OK":
            status = types.ReplicationStatus.HEALTHY
            status_message = f"{repl_source}: Replication is healthy"
        elif protected_path_state in ("syncing", "initializing"):
            status = types.ReplicationStatus.UNKNOWN
            status_message = (
                f"{repl_source}: Replication in progress, state: {protected_path_state}"
            )
        else:
            status = types.ReplicationStatus.DEGRADED
            status_message = (
                f"{repl_source}: Replication state: {protected_path_state}, health: {health}"
            )

        return types.GetVolumeReplicationInfoResp(
            last_sync_time=last_sync_time,
            last_sync_duration=last_sync_duration,
            last_sync_bytes=last_sync_bytes,
            status=status,
            status_message=status_message,
        )


################################################################
#
# NFS Replication Controller
#
################################################################


class NFSReplicationController(BaseReplicationController, Instrumented):
    """CSI-Addons Volume Replication Controller for NFS volumes."""

    volume_type = "NFS"

    def _list_volumes_in_group(self, vms_session, parsed):
        ppath = vms_session.protectedpaths.one(name=parsed.ppath_name, fail_if_missing=True)
        return vms_session.views.list(path__startswith=ppath.source_dir)

    def _get_volume_id(self, volume):
        return os.path.basename(volume["path"])


################################################################
#
# Block Replication Controller
#
################################################################


class BlockReplicationController(BaseReplicationController, Instrumented):
    """CSI-Addons Volume Replication Controller for Block/NVMe-oF volumes."""

    volume_type = "BLOCK"

    def _list_volumes_in_group(self, vms_session, parsed):
        from vast_csi.plugins.volumegroup import BlockVolumeGroupController
        ppath = vms_session.protectedpaths.one(name=parsed.ppath_name, fail_if_missing=True)
        source_dir = ppath.source_dir

        # Reuse BlockVolumeGroupController's subsystem discovery helper.
        helper = BlockVolumeGroupController.__new__(BlockVolumeGroupController)
        subsystem = helper._find_subsystem_for_source_dir(vms_session, source_dir)

        rel_prefix = source_dir[len(subsystem.path):].lstrip("/") or None
        if rel_prefix:
            return vms_session.volumes.list(
                name__contains=rel_prefix,
                subsystem_name=subsystem.name,
            )
        return vms_session.volumes.list(subsystem_name=subsystem.name)

    def _get_volume_id(self, volume):
        return os.path.basename(volume["name"])


################################################################
#
# Serve Function
#
################################################################


def serve(server, conf, plugin: str):
    """Register the appropriate replication controller on the gRPC server."""
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf

    plugin_type = "NFS" if plugin == "replication[nfs]" else "Block"
    logger.info(f"Starting CSI-Addons {plugin_type} Replication Plugin")

    AddonsIdentity.add_replication_capabilities()
    AddonsIdentity.register(server)

    if plugin == "replication[nfs]":
        replication_controller = NFSReplicationController(conf)
    else:
        replication_controller = BlockReplicationController(conf)

    replication_pb2_grpc.add_ControllerServicer_to_server(replication_controller, server)
    logger.info(f"{plugin_type} Volume Replication Controller service registered")
