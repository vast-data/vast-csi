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
from typing import Optional
from datetime import datetime, timezone

from easypy.units import MINUTE, SECOND
from google.protobuf import timestamp_pb2, duration_pb2

from easypy.caching import cached_property

from vast_csi.proto import replication_pb2_grpc
from vast_csi.logging import logger
from vast_csi.plugins.base import Instrumented, AddonsIdentity
from vast_csi.exceptions import Abort,WaitResourceFailed
from vast_csi import csi_types as types
from vast_csi.utils import to_abort
from vast_csi.filesystem_utils import resource_locked

from vast_csi.builders.replication import (
    NFSReplicationBuilder,
    BlockReplicationBuilder,
    BaseReplicationBuilder,
    ReplicationRole,
)
from vast_csi.plugins.volumegroup import _parse_volume_group_id, ID_SUFFIX_LENGTH
from vast_csi.session.resources import WaitCondition

CONF = None


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
                "Cannot get volume_id from volume group source. Use volume_group_id or volume_ids instead.",
            )
        return self._source.volume.volume_id

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
            return [self._source.volume.volume_id]
        else:
            volume_group_id = self._source.volumegroup.volume_group_id
            logger.debug(f"Fetching volume group {volume_group_id} member volume IDs")
            return sorted(self.volumes_mapping.keys())

    def get_protected_path_name(self, suffix: Optional[str] = None):
        """Get the protected path name for a volume or volume group."""
        if not suffix:
            # vg - volume group
            # vo - volume object
            suffix = "vg-" if self.is_volume_group else "vo-"
        return suffix + self.identifier

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

    Contains all common replication logic. Subclasses only need to specify:
    - builder_class: The replication builder to use (NFS or Block)

    The volume_type is automatically determined from the builder_class.
    """

    # Subclasses must override this
    builder_class = None

    def __init__(self, config):
        self.config = config

    @cached_property
    def volume_type(self):
        """Automatically determine a volume type label based on builder_class (used for logging)."""
        return (
            "BLOCK"
            if issubclass(self.builder_class, BlockReplicationBuilder)
            else "NFS"
        )

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
    def _validate_active_ppath_status(cls, ppath):
        """Validate that a protected path is in an active state."""
        current_state = (ppath.get("protected_path_state") or "").lower()
        if current_state != "active":
            failure_reason = ppath.get("failure_reason")
            error_msg = (
                f"Protected path {ppath.name!r} is not in active state: {current_state}"
            )
            if failure_reason:
                error_msg += f" ({failure_reason})"
            raise Abort(types.ABORTED, error_msg)
        return current_state

    @classmethod
    def _wait_for_ppath_active(cls, ppath, vms_session):
        """Wait for a protected path to reach an active state."""
        try:
            cls._validate_active_ppath_status(ppath)
        except Abort as e:
            logger.info(f"{cls.volume_type}: {e}")
            vms_session.protectedpaths.wait_active(ppath.id)

    def _get_source_session_and_ppath(
        self,
        vms_session,
        secondary_vms_session,
        protected_path_name,
    ):
        """
        Determine which cluster is currently SOURCE and return its session and protected path.

        Args:
            vms_session: VAST API session for primary cluster
            secondary_vms_session: VAST API session for secondary cluster
            protected_path_name: Name of the protected path to check

        Returns:
            tuple: (source_session, ppath) where:
                - source_session: VMS session of the cluster that is currently SOURCE
                - ppath: Protected path object from the SOURCE cluster
        """
        # Get a protected path from the primary cluster first
        ppath_primary = vms_session.protectedpaths.wait(name=protected_path_name)

        # Check role to determine which cluster is SOURCE
        role_primary = ReplicationRole.from_string(ppath_primary.get("role"))

        if role_primary.is_source():
            source_session = vms_session
            ppath = ppath_primary
            logger.info(
                f"{self.volume_type}: Primary cluster {source_session!r} is SOURCE"
            )
        else:
            # Check secondary cluster, get protected path from secondary
            ppath_secondary = secondary_vms_session.protectedpaths.wait(
                name=protected_path_name
            )
            role_secondary = ReplicationRole.from_string(ppath_secondary.get("role"))

            if role_secondary.is_source():
                ppath = ppath_secondary
                source_session = secondary_vms_session
                logger.info(
                    f"{self.volume_type}: Secondary cluster {source_session!r} is SOURCE"
                )
            else:
                # Neither cluster is SOURCE/STANDALONE - transition state
                raise Abort(
                    types.ABORTED,
                    f"Protected path {protected_path_name!r} is not yet completed failover transition. "
                    f"Primary role: {role_primary.value}, Secondary role: {role_secondary.value}",
                )

        return source_session, ppath

    def EnableVolumeReplication(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        parameters,
        replication_source,
    ):
        """Enable replication for a volume or volume group."""

        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(f"{self.volume_type}: Enabling replication for {repl_source!r}")
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        # Enable replication for all volumes concurrently
        seen_protected_paths = set()
        for _, ppath, created in self.builder_class.enable_replication(
            repl_source=repl_source,
            vms_session=vms_session,
            configuration=self.config,
            parameters=params,
            secondary_vms_session=secondary_vms_session,
            initial_sync=False,
        ):
            protected_path_name = ppath.name
            # Skip if we've already processed this protected path (e.g., volume group optimization)
            if protected_path_name in seen_protected_paths:
                logger.debug(
                    f"{self.volume_type}: Protected path {protected_path_name} already processed, skipping"
                )
                continue

            with locked.with_message(
                    f"Waiting for protected path {ppath.name!r} to reach active state"
            ):
                self._wait_for_ppath_active(ppath=ppath, vms_session=vms_session)

            seen_protected_paths.add(protected_path_name)
            logger.info(
                f"{self.volume_type}: Protected path {protected_path_name} "
                f"found on {vms_session!r}, ensuring replication is enabled"
            )
            # We don't know which cluster is SOURCE,
            # so we need to get the protected path from both clusters to find out the SOURCE role
            source_session, ppath = self._get_source_session_and_ppath(
                vms_session,
                secondary_vms_session,
                protected_path_name,
            )
            if source_session.protectedpaths.ensure_set_enabled(ppath, True):
                logger.info(
                    f"{self.volume_type}: Replication enabled for "
                    f"protected path {protected_path_name} on SOURCE {source_session!r}"
                )
            else:
                logger.info(
                    f"{self.volume_type}: "
                    f"Replication already enabled for {ppath.name!r}. No action taken."
                )

        # Return immediately without waiting for protected paths to reach the active state.
        return types.EnableVolumeReplicationResp()

    def DisableVolumeReplication(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        parameters,
        replication_source,
    ):
        """Disable replication for a volume or volume group."""

        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(f"{self.volume_type}: Disabling replication for {repl_source}")

        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        ppath_suffix = params.get("ppath_suffix")
        protected_path_name = repl_source.get_protected_path_name(ppath_suffix)
        delete_data_kwargs = dict(
            repl_source=repl_source,
            vms_session=vms_session,
            configuration=self.config,
            parameters=params,
            secondary_vms_session=secondary_vms_session,
        )

        logger.info(
            f"{self.volume_type}: Disabling replication for protected path: {protected_path_name!r}"
        )

        # Determine which cluster is currently SOURCE and disable on that cluster
        try:
            source_session, ppath = self._get_source_session_and_ppath(
                vms_session,
                secondary_vms_session,
                protected_path_name,
            )
        except WaitResourceFailed:
            logger.info(
                f"{self.volume_type}: Protected path {protected_path_name!r} not found. No action taken."
            )
        else:
            if source_session.protectedpaths.ensure_set_enabled(ppath, False):
                logger.info(
                    f"{self.volume_type}: Replication disabled for "
                    f"protected path {protected_path_name} on SOURCE {source_session!r}"
                )

            with locked.with_message(
                f"Waiting for replication snapshots to be deleted for {repl_source}"
            ):
                self.builder_class.delete_replication_snapshots(
                    ppath=ppath,
                    **delete_data_kwargs,
                )
            with locked.with_message(
                    f"Waiting for protected path {ppath.name!r} to be deleted."
            ):
                source_session.protectedpaths.delete_by_id(ppath.id)
                source_session.protectedpaths.wait(
                    name=protected_path_name,
                    condition=WaitCondition.DELETED,
                    timeout=2 * MINUTE,
                    sleep=15 * SECOND,
                )

        with locked.with_message(
                f"Waiting for replicated volumes to be deleted for {repl_source}"
        ):
            self.builder_class.delete_replication_volumes(**delete_data_kwargs)

        return types.DisableVolumeReplicationResp()

    def PromoteVolume(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """
        Promote volume(s) to primary (make them writeable) by performing force failover.
        The secondary cluster becomes the new primary source.

        Args:
            vms_session: VAST API session for primary cluster (auto-injected)
            secondary_vms_session: VAST API session for secondary cluster to be promoted (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            force: Force promotion even if not fully synced
            parameters: Plugin-specific parameters
            replication_source: Source volume or volume group
        """
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(f"{self.volume_type}: Promoting {repl_source} to primary")
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        # Process protected paths (one per volume or one for the group)
        ppath_suffix = params.get("ppath_suffix")
        protected_path_name = repl_source.get_protected_path_name(ppath_suffix)

        logger.info(
            f"{self.volume_type}: Promoting {secondary_vms_session!r} "
            f"to primary: protected_path: {protected_path_name!r}"
        )

        ppath = secondary_vms_session.protectedpaths.wait(name=protected_path_name)
        with locked.with_message(
                f"Waiting for protected path {ppath.name!r} to reach active state"
        ):
            self._wait_for_ppath_active(ppath=ppath, vms_session=secondary_vms_session)

        # Check the current role - only perform failover if not already SOURCE
        current_role = ReplicationRole.from_string(ppath.get("role"))
        logger.info(
            f"{self.volume_type}: {secondary_vms_session!r} - "
            f"protected path {protected_path_name!r}, current role: {current_role.value!r}"
        )

        if current_role.is_destination():
            with locked.with_message(
                f"force_failover(promotion) "
                f"for {repl_source} is not yet completed. Waiting..."
            ), to_abort():
                secondary_vms_session.protectedpaths.force_failover(
                    protected_path_id=ppath.id,
                    wait_failover=True,
                )

        if not current_role.is_source():
            raise Abort(
                types.ABORTED,
                f"{secondary_vms_session} - protected path {protected_path_name!r} "
                f"is not yet completed failover transition. "
                f"Current role: {current_role.value!r}  Expected - {ReplicationRole.SOURCE.value!r}",
            )

        # Finally, make sure replication is enabled on SOURCE cluster
        if secondary_vms_session.protectedpaths.ensure_set_enabled(ppath, True):
            logger.info(
                f"{self.volume_type}: Replication enabled for "
                f"protected path {protected_path_name} on SOURCE {secondary_vms_session!r}"
            )

        return types.PromoteVolumeResp()

    def DemoteVolume(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """
        Demote volume(s) to secondary (make them read-only) by promoting primary back to source.

        This is typically called for failback - returning the original primary cluster
        back to being the source after a failover.

        Args:
            vms_session: VAST API session for primary cluster (auto-injected)
            secondary_vms_session: VAST API session for secondary cluster (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            force: Force demotion
            parameters: Plugin-specific parameters
            replication_source: Source volume or volume group
        """
        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(f"{self.volume_type}: Demoting {repl_source} to secondary")
        locked = exit_stack.enter_context(
            resource_locked(repl_source.identifier, abort_on_error=True),
        )

        # Enable replication for all volumes concurrently
        seen_protected_paths = set()
        for _, ppath, created in self.builder_class.enable_replication(
            repl_source=repl_source,
            vms_session=vms_session,
            configuration=self.config,
            parameters=params,
            secondary_vms_session=secondary_vms_session,
            initial_sync=False,
        ):
            protected_path_name = ppath.name
            # Skip if we've already processed this protected path (e.g., volume group optimization)
            if protected_path_name in seen_protected_paths:
                logger.debug(
                    f"{self.volume_type}: "
                    f"Protected path {protected_path_name} already processed, skipping"
                )
                continue

            with locked.with_message(
                    f"Waiting for protected path {ppath.name!r} to reach active state"
            ):
                self._wait_for_ppath_active(ppath=ppath, vms_session=vms_session)

            seen_protected_paths.add(protected_path_name)
            current_role = ReplicationRole.from_string(ppath.get("role"))
            logger.info(
                f"{self.volume_type}: Demoting {secondary_vms_session!r}, "
                f"protected_path: {protected_path_name}",
            )

            if current_role.is_destination():
                with locked.with_message(
                    f"force_failover(demotion) "
                    f"for {repl_source} is not yet completed. Waiting..."
                ), to_abort():
                    vms_session.protectedpaths.force_failover(
                        protected_path_id=ppath.id,
                        wait_failover=True,
                    )

            if not current_role.is_source():
                raise Abort(
                    types.ABORTED,
                    f"Protected path {protected_path_name} "
                    f"is not yet completed failover transition. "
                    f"Current role: {current_role.value!r}. Expected - {ReplicationRole.SOURCE.value!r}",
                )

            # Finally, make sure replication is enabled on SOURCE cluster
            if vms_session.protectedpaths.ensure_set_enabled(ppath, True):
                logger.info(
                    f"{self.volume_type}: Replication enabled for "
                    f"protected path {protected_path_name} on SOURCE {vms_session!r}"
                )

        return types.DemoteVolumeResp()

    def ResyncVolume(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        parameters,
        replication_source,
        force=False,
    ):
        """
        Resync volume(s) after split-brain or data divergence.

        Triggers immediate replication from the current SOURCE cluster.

        Args:
            vms_session: VAST API session for primary cluster (auto-injected)
            secondary_vms_session: VAST API session for secondary cluster (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            parameters: Plugin-specific parameters
            replication_source: Source volume or volume group
            force: Force resync
        """

        params = self._make_parameters(parameters)
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.info(f"{self.volume_type}: Resyncing {repl_source}")

        exit_stack.enter_context(resource_locked(repl_source.identifier))

        # Process protected paths (one per volume or one for the group)
        ppath_suffix = params.get("ppath_suffix")
        protected_path_name = repl_source.get_protected_path_name(ppath_suffix)

        # Determine which cluster is currently SOURCE
        source_session, ppath = self._get_source_session_and_ppath(
            vms_session,
            secondary_vms_session,
            protected_path_name,
        )
        logger.info(
            f"{self.volume_type}: Triggering resync from {source_session!r}, "
            f"protected_path: {protected_path_name}"
        )

        ppolicy = vms_session.protectionpolicies.get(ppath.protection_policy_id)
        if not ppolicy:
            raise Abort(
                types.NOT_FOUND,
                f"Protection policy {ppath.protection_policy_id} not found",
            )

        time_expires_local, time_expires_target = (
            BaseReplicationBuilder.parse_policy_timestamps(ppolicy)
        )
        source_session.protectedpaths.replicate_now(
            protected_path_id=ppath.id,
            time_expires_local=time_expires_local,
            time_expires_target=time_expires_target,
        )
        logger.info(
            f"{self.volume_type}: Resync triggered for protected path {protected_path_name}"
        )

        # Check if sync is complete (protected_path_state should be "active")
        state = (ppath.get("protected_path_state") or "").lower()
        volume_ready = state == "active"

        return types.ResyncVolumeResp(ready=volume_ready)

    def GetVolumeReplicationInfo(
        self,
        vms_session,
        secondary_vms_session,
        exit_stack,
        replication_source,
    ):
        """
        Get replication status and information for a volume.

        Args:
            vms_session: VAST API session for primary cluster (auto-injected)
            secondary_vms_session: VAST API session for secondary cluster (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            replication_source: Source volume or volume group
        """
        repl_source = self._make_repl_source(replication_source, vms_session)

        logger.debug(f"{self.volume_type}: Getting replication info for {repl_source}")
        identifier = repl_source.identifier
        ppath = None

        # Determine which cluster is currently SOURCE
        ppath_primary = vms_session.protectedpaths.one(
            name__contains=identifier, fail_if_missing=True
        )
        # Check role to determine which cluster is SOURCE
        role_primary = ReplicationRole.from_string(ppath_primary.get("role"))

        if role_primary.is_source():
            ppath = ppath_primary
            logger.info(
                f"{self.volume_type}: Primary cluster {vms_session!r} "
                f"is the active SOURCE, using it for replication info",
            )
        elif role_primary.is_destination():
            # Check if secondary cluster is SOURCE
            ppath_secondary = secondary_vms_session.protectedpaths.one(
                name__contains=identifier, fail_if_missing=True
            )
            role_secondary = ReplicationRole.from_string(ppath_secondary.get("role"))
            logger.info(f"{self.volume_type}: Secondary cluster role: {role_secondary}")

            if role_secondary.is_source():
                ppath = ppath_secondary
                logger.info(
                    f"{self.volume_type}: Secondary cluster {secondary_vms_session!r} "
                    f"is the active SOURCE, using it for replication info",
                )

        # Handle transition state - neither cluster is SOURCE
        if not ppath:
            # Return degraded status indicating transition
            return types.GetVolumeReplicationInfoResp(
                last_sync_time=timestamp_pb2.Timestamp(),
                last_sync_duration=None,
                last_sync_bytes=0,
                status=types.ReplicationStatus.DEGRADED,
                status_message=f"{repl_source}: "
                f"Replication in transition state: {role_primary}, "
                f"no SOURCE cluster available yet",
            )

        last_restore_point_creation_time = ppath.get("last_restore_point_creation_time")
        last_restore_point_time = ppath.get("last_restore_point_time")

        # Initialize response fields
        last_sync_time = timestamp_pb2.Timestamp()
        last_sync_duration = None
        last_sync_bytes = 0  # VAST API doesn't provide this, using 0

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

            # Set last_sync_time to when replication started
            last_sync_time.FromDatetime(start_time)
            duration_seconds = int((end_time - start_time).total_seconds())
            last_sync_duration = duration_pb2.Duration(seconds=duration_seconds)

        # Determine status based on protected path state
        protected_path_state = (ppath.get("protected_path_state") or "").lower()
        health = (ppath.get("health") or "").upper()

        if not last_restore_point_creation_time:
            status = types.ReplicationStatus.UNKNOWN
            status_message = f"{repl_source}: Initial sync not yet completed"
        elif health != "OK":
            status = types.ReplicationStatus.ERROR
            status_message = f"{repl_source}: Protected path health: {health}, failure: {ppath.get('failure_reason', 'unknown')}"
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
            status_message = f"{repl_source}: Replication state: {protected_path_state}, health: {health}"

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
    """
    CSI-Addons Volume Replication Controller for NFS volumes.
    """

    builder_class = NFSReplicationBuilder

    def _list_volumes_in_group(self, vms_session, parsed):
        return vms_session.views.list(path__startswith=parsed.path)

    def _get_volume_id(self, volume):
        return os.path.basename(volume["path"])


################################################################
#
# Block Replication Controller
#
################################################################


class BlockReplicationController(BaseReplicationController, Instrumented):
    """
    CSI-Addons Volume Replication Controller for Block/NVMe-oF volumes.
    """

    builder_class = BlockReplicationBuilder

    def _list_volumes_in_group(self, vms_session, parsed):
        subsystem = vms_session.views.get_subsystem(subsystem=parsed.subsystem_name)
        if not subsystem:
            raise Abort(types.NOT_FOUND, f"Unknown subsystem: {parsed.subsystem_name}")

        base_prefix = None if parsed.path == "/" else parsed.path
        if base_prefix:
            return vms_session.volumes.list(
                name__contains=base_prefix,
                subsystem_name=subsystem.name,
            )
        else:
            return vms_session.volumes.list(
                subsystem_name=subsystem.name,
            )

    def _get_volume_id(self, volume):
        return os.path.basename(volume["name"])


################################################################
#
# Serve Function
#
################################################################


def serve(server, conf, plugin: str):
    """
    Serve function for the CSI-Addons replication plugin.

    This is called when the driver is started with --addons replication[nfs] or replication[block].
    It registers the appropriate replication controller on the provided gRPC server.

    Args:
        server: gRPC server to register services on
        conf: Configuration object
        plugin: Plugin name (e.g., "replication[nfs]" or "replication[block]")
    """
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf

    plugin_type = "NFS" if plugin == "replication[nfs]" else "Block"
    logger.info(f"Starting CSI-Addons {plugin_type} Replication Plugin")

    # Add replication capability to the shared identity
    AddonsIdentity.add_replication_capabilities()
    AddonsIdentity.register(server)

    # Register the appropriate Replication Controller based on plugin type
    if plugin == "replication[nfs]":
        replication_controller = NFSReplicationController(conf)
    else:  # replication[block]
        replication_controller = BlockReplicationController(conf)

    replication_pb2_grpc.add_ControllerServicer_to_server(
        replication_controller, server
    )
    logger.info(f"{plugin_type} Volume Replication Controller service registered")
