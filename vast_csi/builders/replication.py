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
CSI-Addons Volume Replication Builders

Provides builder classes for constructing and executing volume replication operations
such as enable, disable, promote, demote, and resync.
"""
import os
import concurrent.futures
import time
from abc import abstractmethod
from concurrent.futures.thread import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Optional, Dict, Any

from requests.exceptions import HTTPError
from easypy.bunch import Bunch
from vast_csi.builders.addons_base import BaseAddonsBuilder
from vast_csi.exceptions import (
    SourceNotFound,
    PpathConflict,
    MissingParameter,
    VolumeGroupValidationError,
)
from vast_csi.utils import parse_duration_to_timestamp, replace_path_prefix
from vast_csi.logging import logger

# VMS discovers snapshots from EStore via polling every ~15 seconds.
# After disabling a protected path, in-flight snapshots may still be created
# by EStore and only become visible in VMS after the next poll cycle.
# We must wait at least this long before querying/deleting snapshots
# to ensure all pending snapshots have been discovered.
VMS_SNAPSHOT_DISCOVERY_INTERVAL = 15


class ReplicationRole(StrEnum):
    """
    Replication role for protected paths.

    Matches VAST Control::ReplicationGroupRoleState enum.
    """

    # Stable states
    SOURCE = "SOURCE"
    DESTINATION = "DESTINATION"
    STANDALONE = "STANDALONE"
    INVALID = "INVALID"

    # Special values
    NA = "N/A"  # Not applicable / not set

    # Transitional states
    BECOMING_SOURCE = "BECOMING_SOURCE"
    BECOMING_STANDALONE = "BECOMING_STANDALONE"
    BECOMING_DESTINATION = "BECOMING_DESTINATION"
    BECOMING_SOURCE_ASK_FOR_SOURCE = "BECOMING_SOURCE_ASK_FOR_SOURCE"
    BECOMING_SOURCE_ATTACHING_MEMBERS = "BECOMING_SOURCE_ATTACHING_MEMBERS"
    BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS = "BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS"
    BECOMING_SOURCE_GRACEFULLY_FAILING_OVER = "BECOMING_SOURCE_GRACEFULLY_FAILING_OVER"

    # Fallback for future unknown roles
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, value: str) -> "ReplicationRole":
        """
        Parse ReplicationRole from string.

        Handles unknown roles gracefully by returning UNKNOWN instead of raising KeyError.
        This allows the code to work with future VAST roles without breaking.
        """
        if not value:
            return cls.UNKNOWN

        # Special case: "N/A" (case insensitive) maps to the NA enum member
        if value.upper() == "N/A":
            return cls.NA

        normalized = value.upper().replace(" ", "_")
        try:
            return cls[normalized]
        except KeyError:
            logger.warning(f"Unknown replication role: {value!r}")
            return cls.UNKNOWN

    def is_source(self) -> bool:
        """Check if this role represents the source cluster."""
        return self == ReplicationRole.SOURCE

    def is_destination(self) -> bool:
        """Check if this role represents the destination cluster."""
        return self == ReplicationRole.DESTINATION

    def is_transitional(self) -> bool:
        """Check if this role represents a transitional state (BECOMING_*)."""
        return self.value.startswith("BECOMING_")

    def is_stable(self) -> bool:
        """Check if this role represents a stable state (SOURCE, DESTINATION, STANDALONE)."""
        return self in (
            ReplicationRole.SOURCE,
            ReplicationRole.DESTINATION,
            ReplicationRole.STANDALONE,
        )


__all__ = [
    "NFSReplicationBuilder",
    "BlockReplicationBuilder",
    "BaseReplicationBuilder",
    "ReplicationRole",
]


@dataclass
class BaseReplicationBuilder(BaseAddonsBuilder):
    """Base builder for replication operations with common functionality.

    This builder works with sessions auto-injected by the Instrumented wrapper.

    Attributes:
        vms_session: Source VMS session (auto-injected)
        secondary_vms_session: Destination VMS session (auto-injected)
        configuration: Configuration object
        volume_id: Volume identifier for the replication operation
        repl_source: ReplicationSource wrapper with volume/volumegroup information
        protection_policy: Name of pre-existing protection policy
        sync_interval_seconds: Sync interval in seconds (default: 900)
        initial_sync: Internal flag - always True when enabling replication to trigger immediate sync
        ppath_suffix: Optional suffix for protected path name
        secondary_qos_policy: QoS policy name for destination resources
        secondary_qos_policy_id: QoS policy ID for destination resources
        group_ppath: Pre-created protected path from volume group optimization
        ppath_was_created: Indicates if group_ppath was newly created
    """

    # Common parameters for all replication types
    vms_session: "RESTSession"
    secondary_vms_session: "RESTSession"
    configuration: "CONF"
    volume_id: str
    repl_source: "ReplicationSource"  # provides volume/group context
    protection_policy: str
    sync_interval_seconds: int
    initial_sync: bool
    ppath_suffix: str = None
    group_ppath: Optional[Bunch] = None  # Pre-created protected path from volume group
    secondary_qos_policy: str = None
    secondary_qos_policy_id: int = None
    ppath_was_created: bool = False
    delete_destination_snapshots: bool = False
    delete_destination_volumes: bool = False

    @property
    def protected_path_name(self) -> str:
        """Compute the protected path name from volume_id and optional suffix."""
        return self.repl_source.get_protected_path_name(self.ppath_suffix)

    @classmethod
    def parse_common_params(cls, parameters: Dict[str, Any]) -> dict:
        """Parse common replication parameters shared by all replication types.

        Args:
            parameters: Replication parameters from VolumeReplicationClass

        Returns:
            Dictionary with parsed common parameters
        """
        # Parse required parameters
        sync_interval_seconds = int(
            cls._get_required_param(parameters, "sync_interval_seconds")
        )
        protection_policy = cls._get_required_param(parameters, "protection_policy")

        # Parse optional parameters
        ppath_suffix = parameters.get("ppath_suffix") or None
        secondary_qos_policy = parameters.get("secondary_qos_policy")
        if "secondary_qos_policy_id" in parameters:
            secondary_qos_policy_id = int(parameters.get("secondary_qos_policy_id"))
        else:
            secondary_qos_policy_id = None

        delete_destination_snapshots = cls._get_bool_param(
            parameters, "delete_destination_snapshots"
        )
        delete_destination_volumes = cls._get_bool_param(
            parameters, "delete_destination_volumes"
        )

        return dict(
            ppath_suffix=ppath_suffix,
            sync_interval_seconds=sync_interval_seconds,
            protection_policy=protection_policy,
            secondary_qos_policy=secondary_qos_policy,
            secondary_qos_policy_id=secondary_qos_policy_id,
            delete_destination_snapshots=delete_destination_snapshots,
            delete_destination_volumes=delete_destination_volumes,
        )

    @staticmethod
    def parse_policy_timestamps(ppolicy):
        """Extract and parse timestamps from protection policy.

        Args:
            ppolicy: Protection policy object with frames containing keep-local and keep-remote

        Returns:
            tuple: (time_expires_local, time_expires_target) as timestamp strings
        """
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
            logger.warning(
                f"Failed to parse duration from protection policy: {e}. Using defaults."
            )
            time_expires_local = parse_duration_to_timestamp("1H")
            time_expires_target = parse_duration_to_timestamp("1H")

        return time_expires_local, time_expires_target

    @abstractmethod
    def enable_volume_group_replication(
        self,
        repl_source: "ReplicationSource",
    ) -> Bunch:
        """
        Enable volume group replication by finding a common base path.
        
        This method is strict: all volumes must share the same base path/subsystem.
        If not, it raises an error instead of falling back to per-volume replication.

        Args:
            repl_source: ReplicationSource with volume group information

        Returns:
            Protected path object
        """
        pass

    @abstractmethod
    def delete_volume(self):
        """Delete a single replicated volume from the cluster."""

    @classmethod
    def enable_replication(
        cls,
        repl_source: "ReplicationSource",
        vms_session: "RESTSession",
        configuration: "CONF",
        parameters: Dict[str, Any],
        secondary_vms_session: "RESTSession",
        initial_sync: bool = True,
    ):
        """
        Enable replication for a volume or volume group.

        Creates a builder instance for each volume_id from the replication source
        and executes them in parallel. Yields (volume_id, ppath, created) tuples
        as each completes.

        Args:
            repl_source: ReplicationSource wrapper with volume/volumegroup information
            vms_session: Source VAST API session
            configuration: Configuration object
            parameters: Replication parameters from VolumeReplicationClass
            secondary_vms_session: Destination VAST API session
            initial_sync: If True, trigger immediate replication (default: True)

        Yields:
            Tuple of (volume_id, ppath, created) for each completed volume
        """

        group_ppath = None
        ppath_was_created = False

        # Try volume group optimization if this is a volume group
        if repl_source.is_volume_group:
            group_builder = cls.from_parameters(
                vms_session=vms_session,
                configuration=configuration,
                volume_id=repl_source.volume_group_id,
                repl_source=repl_source,
                parameters=parameters,
                secondary_vms_session=secondary_vms_session,
                initial_sync=initial_sync,
            )
            group_ppath = group_builder.enable_volume_group_replication(
                repl_source=repl_source,
            )
            ppath_was_created = group_builder.ppath_was_created

        # Execute a builder for each volume (to create views, quotas, volumes)
        # Pass group_ppath if available to skip per-volume protected path creation
        def execute_for_volume(volume_id: str):
            params = dict(
                vms_session=vms_session,
                configuration=configuration,
                volume_id=volume_id,
                repl_source=repl_source,
                parameters=parameters,
                secondary_vms_session=secondary_vms_session,
                initial_sync=initial_sync,
                group_ppath=group_ppath,
                ppath_was_created=ppath_was_created,
            )

            builder = cls.from_parameters(**params)
            ppath_result, created_result = builder.execute()
            return volume_id, ppath_result, created_result

        # Even in case of group replication
        # we still need to create quotas/views/volumes per PVC if flags are set
        volume_ids = repl_source.volume_ids
        max_workers = min(len(volume_ids), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_volume = {
                executor.submit(execute_for_volume, volume_id): volume_id
                for volume_id in volume_ids
            }

            # Yield results as they complete
            for future in concurrent.futures.as_completed(future_to_volume):
                volume_id = future_to_volume[future]
                try:
                    result = future.result()
                    yield result
                except Exception as e:
                    logger.error(
                        f"Failed to enable replication for volume {volume_id}: {e}"
                    )
                    raise


    @classmethod
    def delete_replication_snapshots(
        cls,
        ppath: "Ppath",
        repl_source: "ReplicationSource",
        vms_session: "RESTSession",
        configuration: "CONF",
        parameters: Dict[str, Any],
        secondary_vms_session: "RESTSession",
    ):
        """
        Delete replication snapshots on both primary and secondary clusters.

        Args:
            ppath: Protected path object (provides source_dir, target_exported_dir, protection_policy_name)
            repl_source: ReplicationSource wrapper with volume/volumegroup information
            vms_session: Primary VAST API session
            configuration: Configuration object
            parameters: Replication parameters from VolumeReplicationClass
            secondary_vms_session: Secondary VAST API session
        """
        builder = cls.from_parameters(
            vms_session=vms_session,
            configuration=configuration,
            volume_id=repl_source.identifier,
            repl_source=repl_source,
            parameters=parameters,
            secondary_vms_session=secondary_vms_session,
        )
        if not builder.delete_destination_snapshots:
            logger.info("Skipping snapshot deletion (delete_destination_snapshots=false)")
            return

        def _delete_snapshots(path, ppolicy_name, session):
            path = path.rstrip("/") + "/"
            entries = session.snapshots.list(
                path=path,
                protection_policy__name=ppolicy_name,
            )
            for entry in entries:
                try:
                    session.snapshots.delete_by_id(entry.id)
                except HTTPError as exc:
                    if exc.response.status_code == 404:
                        logger.info(f"Entry {entry.id} not found, skipping delete")
                    else:
                        raise

        logger.info(
            f"Waiting {VMS_SNAPSHOT_DISCOVERY_INTERVAL}s for VMS to discover "
            f"any in-flight snapshots before deletion"
        )
        time.sleep(VMS_SNAPSHOT_DISCOVERY_INTERVAL)

        ppolicy_name = ppath.protection_policy_name
        _delete_snapshots(
            path=ppath.source_dir,
            ppolicy_name=ppolicy_name,
            session=vms_session,
        )
        _delete_snapshots(
            path=ppath.target_exported_dir,
            ppolicy_name=ppolicy_name,
            session=secondary_vms_session,
        )

    @classmethod
    def delete_replication_volumes(
        cls,
        repl_source: "ReplicationSource",
        vms_session: "RESTSession",
        configuration: "CONF",
        parameters: Dict[str, Any],
        secondary_vms_session: "RESTSession",
    ):
        """
        Delete replicated volumes on the secondary cluster in parallel.

        Creates a builder instance per volume via from_parameters and calls
        delete_volume on each.

        Args:
            repl_source: ReplicationSource wrapper with volume/volumegroup information
            vms_session: Primary VAST API session
            configuration: Configuration object
            parameters: Replication parameters from VolumeReplicationClass
            secondary_vms_session: Secondary VAST API session
        """
        volume_ids = repl_source.volume_ids
        if not volume_ids:
            return

        def delete_one(volume_id: str):
            builder = cls.from_parameters(
                vms_session=vms_session,
                configuration=configuration,
                volume_id=volume_id,
                repl_source=repl_source,
                parameters=parameters,
                secondary_vms_session=secondary_vms_session,
            )
            if not builder.delete_destination_volumes:
                logger.info(
                    f"Skipping volume deletion for {volume_id!r} (delete_destination_volumes=false)"
                )
                return volume_id
            builder.delete_volume()
            return volume_id

        max_workers = min(len(volume_ids), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_volume = {
                executor.submit(delete_one, volume_id): volume_id
                for volume_id in volume_ids
            }
            for future in concurrent.futures.as_completed(future_to_volume):
                volume_id = future_to_volume[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(
                        f"Failed to delete replicated volume {volume_id}: {e}"
                    )
                    raise


@dataclass
class NFSReplicationBuilder(BaseReplicationBuilder):
    """Builder for enabling NFS volume replication.

    NFS-specific attributes:
        secondary_storage_path: Base prefix for replicated data on the destination cluster
        secondary_view_policy: View policy for destination views (required if create_view=True)
        secondary_tenant_name: Tenant name on destination cluster (alternative to secondary_view_policy)
        create_view: If True, create view on destination cluster
        create_quota: If True, create quota on destination cluster
    """

    # NFS-specific parameters
    secondary_storage_path: str = None
    secondary_view_policy: str = None
    secondary_tenant_name: str = None
    create_view: bool = False
    create_quota: bool = False

    def delete_volume(self):
        if self.create_quota:
            if quota := self.secondary_vms_session.quotas.one(name=self.volume_id):
                self.secondary_vms_session.quotas.delete_by_id(quota.id)
                logger.info(f"Deleted quota {self.volume_id!r}")
        if self.create_view:
            self.secondary_vms_session.views.delete(path__contains=self.volume_id)
            logger.info(f"Deleted view for {self.volume_id!r}")

    def enable_volume_group_replication(
        self,
        repl_source: "ReplicationSource",
    ) -> Bunch:
        """
        Enable NFS volume group replication by checking if all volumes
        share a common base directory (view path).
        
        This is strict: all volumes MUST share the same base directory.
        If not, an error is raised.

        Args:
            repl_source: ReplicationSource with volume group information
            
        Returns:
            Protected path object
        """

        # Get metadata from volume group ID (already validated during creation)
        base_dir = repl_source.parsed.path

        if ppath := self.vms_session.protectedpaths.one(source_dir=base_dir):
            if ppath.name == self.protected_path_name:
                return ppath
            raise PpathConflict(
                requested_name=self.protected_path_name,
                existing_name=ppath.name,
                source_dir=base_dir,
            )

        logger.info(
            f"NFS volume group: checking if all "
            f"{len(repl_source.volume_ids)} volumes share base directory {base_dir}"
        )

        # Use cached property - no API call needed!
        ids_by_base_dir = set(repl_source.volumes_mapping.keys())

        # Check if all volume IDs are in the base directory (STRICT)
        missing_volumes = []
        for vol_id in repl_source.volume_ids:
            if vol_id not in ids_by_base_dir:
                missing_volumes.append(vol_id)
        
        if missing_volumes:
            raise VolumeGroupValidationError(
                resource_type="base directory",
                path=base_dir,
                missing_volumes=missing_volumes,
                found_volumes=list(ids_by_base_dir),
            )

        ppolicy = self.vms_session.protectionpolicies.one(
            name=self.protection_policy,
            fail_if_missing=True,
        )

        # Get a secondary tenant (either from view policy or directly by name)
        if self.secondary_view_policy:
            secondary_view_policy = self.secondary_vms_session.viewpolicies.one(
                name=self.secondary_view_policy,
                fail_if_missing=True,
            )
            secondary_tenant = self.secondary_vms_session.tenants.get(
                secondary_view_policy.tenant_id,
            )
        elif self.secondary_tenant_name:
            secondary_tenant = self.secondary_vms_session.tenants.one(
                name=self.secondary_tenant_name,
                fail_if_missing=True,
            )
        else:
            raise Exception(
                "Either secondary_view_policy or secondary_tenant_name must be provided"
            )

        # Compute target base directory for a volume group.
        # replace_path_prefix() replaces the first N segments of base_dir with secondary_storage_path,
        # where N is the number of segments in secondary_storage_path. This handles various scenarios:
        #
        # 1. secondary_storage_path is None/empty:
        #    - Returns base_dir unchanged (one-to-one path mapping)
        #    - Example: base_dir="/k8s/volumes" → target="/k8s/volumes"
        #
        # 2. secondary_storage_path is shorter (fewer segments):
        #    - Replaces first N segments, keeps remaining from base_dir
        #    - Example: base_dir="/foo/bar/biz", secondary_storage_path="/zoo"
        #              → target="/zoo/bar/biz" (replaced 1 segment, kept 2)
        #
        # 3. secondary_storage_path is the same length:
        #    - Replaces all matching segments, keeps remaining
        #    - Example: base_dir="/foo/bar/biz", secondary_storage_path="/zoo/rar"
        #              → target="/zoo/rar/biz" (replaced 2 segments, kept 1)
        #
        # 4. secondary_storage_path is longer (more segments than base_dir):
        #    - Uses secondary_storage_path directly (replaces entire path)
        #    - Example: base_dir="/k8s", secondary_storage_path="/backup/dr-site/volumes"
        #              → target="/backup/dr-site/volumes" (base_dir has 1 segment, replacement has 3)
        dest_dir = replace_path_prefix(base_dir, self.secondary_storage_path)

        ppath = self.vms_session.protectedpaths.create(
            name=self.protected_path_name,
            source_dir=base_dir,
            tenant_id=ppolicy.tenant_id,
            target_exported_dir=dest_dir,
            protection_policy_id=ppolicy.id,
            remote_tenant_guid=secondary_tenant.guid,
            sync_interval=self.sync_interval_seconds,
            capabilities="ASYNC_REPLICATION",
        )

        # Mark that the protected path was created (for child builders)
        self.ppath_was_created = True

        logger.info(
            f"Successfully created protected path for base directory {base_dir}"
        )
        return ppath

    @classmethod
    def compute_target_directory(
        cls,
        volume_id: str,
        secondary_storage_path: str,
        source_view_path: str,
    ) -> str:
        """
        Compute the target exported directory for replication.

        Handles three cases:
        1. Static volume: volume_id starts with "/" - use volume_id directly
        2. Different prefix: secondary_storage_path is provided - join with volume_id
        3. Same path: use source_view_path as fallback (one to one mapping)

        Args:
            volume_id: Volume identifier
            secondary_storage_path: Optional base path on destination cluster
            source_view_path: Source view path (used as fallback)

        Returns:
            Target directory path for the destination cluster
        """
        if volume_id.startswith("/"):
            # Static volume: use volume_id directly as target
            return volume_id
        elif secondary_storage_path:
            # Different prefix: join secondary storage path with volume_id
            return os.path.join(secondary_storage_path, volume_id)
        else:
            # Same path: replicate to the same path as a source
            return source_view_path

    @classmethod
    def from_parameters(
        cls,
        vms_session: "RESTSession",
        configuration: "Config",
        volume_id: str,
        repl_source: "ReplicationSource",
        parameters: Dict[str, Any],
        secondary_vms_session: "RESTSession",
        initial_sync: bool = True,
        group_ppath: Optional[Bunch] = None,
        ppath_was_created: bool = False,
        **kwargs,
    ) -> "NFSReplicationBuilder":
        """Parse parameters and create an NFS replication builder instance.

        Args:
            vms_session: Source VAST API session (auto-injected)
            configuration: Configuration object from the plugin
            volume_id: Volume identifier for the replication operation
            repl_source: ReplicationSource wrapper with volume/volumegroup information (REQUIRED)
            parameters: Replication parameters from VolumeReplicationClass
            secondary_vms_session: Destination VAST API session (auto-injected, required)
            initial_sync: If True, trigger immediate replication (default: True)
            group_ppath: Pre-created protected path from volume group.
                        If provided, skips individual volume protected path creation.
            ppath_was_created: Indicates if group_ppath was newly created (True) or already existed (False)
            **kwargs: Additional keyword arguments

        Returns:
            NFSReplicationBuilder instance with parsed parameters
        """
        common_params = cls.parse_common_params(parameters)

        # Parse NFS-specific parameters
        secondary_view_policy = parameters.get("secondary_view_policy")
        secondary_tenant_name = parameters.get("secondary_tenant_name")
        secondary_storage_path = parameters.get("secondary_storage_path", "")
        create_view = cls._get_bool_param(parameters, "create_view")
        create_quota = cls._get_bool_param(parameters, "create_quota")

        # secondary_view_policy is required if create_view is True
        if create_view and not secondary_view_policy:
            raise ValueError("secondary_view_policy is required when create_view=true")

        # either secondary_view_policy or secondary_tenant_name must be provided
        if not secondary_view_policy and not secondary_tenant_name:
            raise ValueError(
                "Either secondary_view_policy or secondary_tenant_name must be provided"
            )

        return cls(
            vms_session=vms_session,
            configuration=configuration,
            volume_id=volume_id,
            repl_source=repl_source,
            secondary_vms_session=secondary_vms_session,
            secondary_storage_path=secondary_storage_path,
            secondary_view_policy=secondary_view_policy,
            secondary_tenant_name=secondary_tenant_name,
            create_view=create_view,
            create_quota=create_quota,
            initial_sync=initial_sync,
            group_ppath=group_ppath,
            ppath_was_created=ppath_was_created,
            **common_params,
        )

    def execute(self, **kwargs):
        """Enable replication for the volume.

        Implements replication using VAST protection policies and protected paths.
        All parameters are pre-parsed in BaseReplicationBuilder.from_parameters()

        If group_ppath is provided - skip
        protected path creation and only handle views/quotas.

        Returns:
            Tuple of (ppath, ppath_was_created) where ppath_was_created indicates
            if the protected path was newly created (True) or already existed (False).
        """

        source_view = None
        create_view = self.create_view
        create_quota = self.create_quota

        if self.group_ppath:
            ppath = self.group_ppath
            created = self.ppath_was_created
            role = ReplicationRole.from_string(ppath.get("role"))
            if not role.is_destination() or (not create_view and not create_quota):
                return ppath, created

        elif ppath := self.vms_session.protectedpaths.one(
            name=self.protected_path_name
        ):
            role = ReplicationRole.from_string(ppath.get("role"))
            if not role.is_destination() or (not create_view and not create_quota):
                return ppath, self.ppath_was_created
        else:
            source_view = self.vms_session.views.one(
                path__contains=self.volume_id,
                fail_if_missing=True,
            )
            ppolicy = self.vms_session.protectionpolicies.one(
                name=self.protection_policy,
                fail_if_missing=True,
            )

            target_dir = self.compute_target_directory(
                volume_id=self.volume_id,
                secondary_storage_path=self.secondary_storage_path,
                source_view_path=source_view.path,
            )

            logger.info(f"Target directory: {target_dir}")

            # Get a secondary tenant (either from view policy or directly by name)
            if self.secondary_view_policy:
                secondary_view_policy = self.secondary_vms_session.viewpolicies.one(
                    name=self.secondary_view_policy,
                    fail_if_missing=True,
                )
                secondary_tenant = self.secondary_vms_session.tenants.get(
                    secondary_view_policy.tenant_id,
                )
            else:
                secondary_tenant = self.secondary_vms_session.tenants.one(
                    name=self.secondary_tenant_name,
                    fail_if_missing=True,
                )

            ppath = self.vms_session.protectedpaths.create(
                name=self.protected_path_name,
                source_dir=source_view.path,
                tenant_id=source_view.tenant_id,
                target_exported_dir=target_dir,
                protection_policy_id=ppolicy.id,
                remote_tenant_guid=secondary_tenant.guid,
                sync_interval=self.sync_interval_seconds,
                capabilities="ASYNC_REPLICATION",
            )
            self.ppath_was_created = True
            role = ReplicationRole.from_string(ppath.get("role"))

        # Create a view on the destination cluster (if requested)
        if role.is_destination() and create_view:
            if not source_view:
                source_view = self.vms_session.views.one(
                    path__contains=self.volume_id,
                    fail_if_missing=True,
                )

            target_dir = self.compute_target_directory(
                volume_id=self.volume_id,
                secondary_storage_path=self.secondary_storage_path,
                source_view_path=source_view.path,
            )

            logger.info(f"Creating view on destination cluster: {target_dir}")
            secondary_view = self.secondary_vms_session.views.ensure(
                path=target_dir,
                protocols=source_view.protocols,
                view_policy=self.secondary_view_policy,
                qos_policy=self.secondary_qos_policy,
                qos_policy_id=self.secondary_qos_policy_id,
            )

            # Create a quota on the destination cluster (if requested and source has quota)
            if create_quota:
                if source_quota := self.vms_session.quotas.one(path=source_view.path):
                    logger.info(
                        f"Creating quota on destination cluster for {target_dir}"
                    )
                    self.secondary_vms_session.quotas.ensure(
                        volume_id=source_quota.name,
                        view_path=target_dir,
                        tenant_id=secondary_view.tenant_id,
                        requested_capacity=source_quota.hard_limit,
                    )
                else:
                    logger.info(
                        f"No source quota found for {source_view.path}, skipping quota creation"
                    )
            else:
                if not create_quota:
                    logger.info(f"Skipping quota creation (create_quota=false)")

        return ppath, self.ppath_was_created


@dataclass
class BlockReplicationBuilder(BaseReplicationBuilder):
    """Builder for enabling block volume replication.

    Block-specific attributes:
        secondary_subsystem: Subsystem name on destination cluster
        secondary_tenant_name: Tenant name on destination cluster
        create_volume: If True, create block volume on destination cluster
    """

    # Block-specific parameters
    secondary_subsystem: str = None
    secondary_tenant_name: str = None

    def delete_volume(self):
        try:
            self.secondary_vms_session.volumes.delete(name__endswith=self.volume_id)
            logger.info(f"Deleted volume {self.volume_id!r}")
        except HTTPError as exc:
            if exc.response.status_code != 404:
                raise

    def enable_volume_group_replication(
        self,
        repl_source: "ReplicationSource",
    ) -> Bunch:
        """
        Enable block volume group replication by checking if all volumes
        share a common subsystem.
        
        This is strict: all volumes MUST share the same subsystem and prefix.
        If not, an error is raised.

        Args:
            repl_source: ReplicationSource with volume group information
            
        Returns:
            Protected path object
        """

        parsed = repl_source.parsed
        subsystem_name = parsed.subsystem_name
        base_prefix = None if parsed.path == "/" else parsed.path

        # Get subsystem by name
        subsystem = self.vms_session.views.get_subsystem(subsystem=subsystem_name)
        if not subsystem:
            raise SourceNotFound(f"Unknown subsystem: {subsystem_name}")

        subsystem_path = subsystem.path

        logger.info(
            f"detected base prefix '{base_prefix}' in volume group metadata, "
            f"checking if all {len(repl_source.volume_ids)} volumes share subsystem {subsystem_path}"
            f"{f' and prefix {base_prefix}' if base_prefix else ''}"
        )

        # Use cached property - no API call needed!
        ids_in_subsystem = set(repl_source.volumes_mapping.keys())

        # Check if all volume IDs from the replication source are found (STRICT)
        missing_volumes = []
        for vol_id in repl_source.volume_ids:
            if vol_id not in ids_in_subsystem:
                missing_volumes.append(vol_id)
        
        if missing_volumes:
            raise VolumeGroupValidationError(
                resource_type="subsystem and prefix",
                subsystem=subsystem_name,
                path=subsystem_path,
                prefix=base_prefix or "(root)",
                missing_volumes=missing_volumes,
                found_volumes=list(ids_in_subsystem),
            )

        # Calculate source and target directories based on base prefix
        # If prefix exists: replicate subsystem_path/base_prefix
        # If no prefix: replicate entire subsystem_path (root)
        if base_prefix:
            source_dir = os.path.join(subsystem_path, base_prefix)
        else:
            source_dir = subsystem_path

        if ppath := self.vms_session.protectedpaths.one(source_dir=source_dir):
            if ppath.name == self.protected_path_name:
                return ppath
            raise PpathConflict(
                requested_name=self.protected_path_name,
                existing_name=ppath.name,
                source_dir=source_dir,
            )

        # Get protection policy
        ppolicy = self.vms_session.protectionpolicies.one(
            name=self.protection_policy,
            fail_if_missing=True,
        )

        if self.secondary_tenant_name:
            # get a secondary tenant by provided name
            secondary_tenant = self.secondary_vms_session.tenants.one(
                name=self.secondary_tenant_name,
                fail_if_missing=True,
            )
        else:
            # assumed that the secondary tenant is the same as the primary tenant
            secondary_tenant = self.secondary_vms_session.tenants.one(
                name=subsystem.tenant_name,
                fail_if_missing=True,
            )

        if base_prefix:
            secondary_subsystem_name = self.secondary_subsystem or subsystem_name
            secondary_subsystem = self.secondary_vms_session.views.get_subsystem(
                subsystem=secondary_subsystem_name,
                tenant_id=secondary_tenant.id,
            )
            if not secondary_subsystem:
                raise SourceNotFound(
                    f"Unknown secondary subsystem: {secondary_subsystem_name}"
                )
            dest_dir = os.path.join(secondary_subsystem.path, base_prefix)
        else:
            dest_dir = source_dir

        ppath = self.vms_session.protectedpaths.create(
            name=self.protected_path_name,
            source_dir=source_dir,
            tenant_id=subsystem.tenant_id,
            target_exported_dir=dest_dir,
            protection_policy_id=ppolicy.id,
            remote_tenant_guid=secondary_tenant.guid,
            sync_interval=self.sync_interval_seconds,
            capabilities="ASYNC_REPLICATION",
        )

        # Mark that the protected path was created (for child builders)
        self.ppath_was_created = True

        # Log success with volume list
        logger.info(
            f"successfully created group protected path "
            f"{source_dir=}, {dest_dir=} - {self.vms_session} <-> {self.secondary_vms_session} for volumes:"
        )
        for vol_id in repl_source.volume_ids:
            logger.info(f"  - {vol_id}")

        return ppath

    @classmethod
    def from_parameters(
        cls,
        vms_session: "RESTSession",
        configuration: "Config",
        volume_id: str,
        repl_source: "ReplicationSource",
        parameters: Dict[str, Any],
        secondary_vms_session: "RESTSession",
        initial_sync: bool = True,  # Can be overridden at call site
        group_ppath: Optional[Bunch] = None,
        ppath_was_created: bool = False,
        **kwargs,
    ) -> "BlockReplicationBuilder":
        """Parse parameters and create a block replication builder instance.

        Args:
            vms_session: Source VAST API session (auto-injected)
            configuration: Configuration object from the plugin
            volume_id: Volume identifier for the replication operation
            repl_source: ReplicationSource wrapper with volume/volumegroup information (REQUIRED)
            parameters: Replication parameters from VolumeReplicationClass
            secondary_vms_session: Destination VAST API session (auto-injected, required)
            initial_sync: If True, trigger immediate replication (default: True)
            group_ppath: Pre-created protected path from volume group optimization.
                        If provided, skips individual volume path creation.
            ppath_was_created: Indicates if group_ppath was newly created (True) or already existed (False)
            **kwargs: Additional keyword arguments

        Returns:
            BlockReplicationBuilder instance with parsed parameters
        """
        # Parse common parameters
        common_params = cls.parse_common_params(parameters)

        # Parse block-specific parameters
        secondary_subsystem = parameters.get("secondary_subsystem")
        secondary_tenant_name = parameters.get("secondary_tenant_name")

        return cls(
            vms_session=vms_session,
            configuration=configuration,
            volume_id=volume_id,
            repl_source=repl_source,
            secondary_vms_session=secondary_vms_session,
            secondary_subsystem=secondary_subsystem,
            secondary_tenant_name=secondary_tenant_name,
            initial_sync=initial_sync,
            group_ppath=group_ppath,
            ppath_was_created=ppath_was_created,
            **common_params,
        )

    def execute(self, **kwargs):
        """Enable replication for the volume.

        If group_ppath is provided (from volume group optimization), skip
        protected path creation and only handle volume creation.

        Returns:
            Tuple of (ppath, ppath_was_created) where ppath_was_created indicates
            if the protected path was newly created (True) or already existed (False).
        """

        created = False
        # For volume groups: parsed.path == "/" means subsystem-level replication
        # where destination subsystem and volumes are created under the hood (no need to create volume).
        # For single volumes: always create volume on secondary.
        if self.repl_source.is_volume_group:
            create_volume = self.repl_source.parsed.path != "/"
        else:
            create_volume = True

        # Use optimized ppath if available, otherwise check/create per-volume
        if self.group_ppath:
            ppath = self.group_ppath
            created = self.ppath_was_created
            role = ReplicationRole.from_string(ppath.get("role"))
            if not role.is_destination() or not create_volume:
                # No sense to check further. Primary system is SOURCE so secondary is DESTINATION.
                # We can't create a volume on the secondary system because it is read only.
                return ppath, created

        elif ppath := self.vms_session.protectedpaths.one(
            name=self.protected_path_name
        ):
            role = ReplicationRole.from_string(ppath.get("role"))
            if not role.is_destination() or not create_volume:
                # No sense to check further. Primary system is SOURCE so secondary is DESTINATION.
                # We can't create a volume on the secondary system because it is read only.
                return ppath, created
        if self.repl_source.is_volume_group:
            # Optimization for volume groups: retrieve volumes from mapping which is cached property
            source_volume = self.repl_source.volumes_mapping.get(self.volume_id)
        else:
            source_volume = self.vms_session.volumes.one(name__endswith=self.volume_id)
        if not source_volume:
            raise SourceNotFound(f"Unknown volume: {self.volume_id}")
        if not (
            source_subsystem := self.vms_session.views.get_subsystem_by_id(
                _id=source_volume.view_id
            )
        ):
            raise SourceNotFound(f"Unknown subsystem: {source_volume.view_id}")
        # Full path is a concatenation of view path and volume name.
        source_dir = os.path.join(source_subsystem.path, source_volume.name.lstrip("/"))

        secondary_subsystem = None
        if create_volume:
            secondary_subsystem_name = self.secondary_subsystem or source_subsystem.name
            secondary_subsystem = self.secondary_vms_session.views.get_subsystem(
                subsystem=secondary_subsystem_name,
                tenant_name=self.secondary_tenant_name,
            )
            dest_dir = os.path.join(
                secondary_subsystem.path, source_volume.name.lstrip("/")
            )
        else:
            dest_dir = source_dir

        if secondary_subsystem:
            secondary_tenant = self.secondary_vms_session.tenants.get(
                secondary_subsystem.tenant_id,
            )
        elif self.secondary_tenant_name:
            # Get a secondary tenant by provided name
            secondary_tenant = self.secondary_vms_session.tenants.one(
                name=self.secondary_tenant_name,
                fail_if_missing=True,
            )
        else:
            raise MissingParameter("secondary_tenant_name")

        if not ppath:
            ppolicy = self.vms_session.protectionpolicies.one(
                name=self.protection_policy,
                fail_if_missing=True,
            )

            ppath = self.vms_session.protectedpaths.create(
                name=self.protected_path_name,
                source_dir=source_dir,
                tenant_id=source_subsystem.tenant_id,
                target_exported_dir=dest_dir,
                protection_policy_id=ppolicy.id,
                remote_tenant_guid=secondary_tenant.guid,
                sync_interval=self.sync_interval_seconds,
                capabilities="ASYNC_REPLICATION",
            )
            created = True
            current_state = (ppath.get("protected_path_state") or "unknown").lower()
            logger.info(
                f"successfully created protected path "
                f"{source_dir}  {self.vms_session} <-> {self.secondary_vms_session} (state: '{current_state}')",
            )

        role = ReplicationRole.from_string(ppath.get("role"))

        # Create destination volume (if requested and role is DESTINATION)
        if role.is_destination() and create_volume:
            logger.info(f"Creating volume on destination cluster: {source_volume.name!r}")
            qos_policy_id = self.secondary_qos_policy_id
            if self.secondary_qos_policy:
                qos_policy_id = self.secondary_vms_session.quospolicies.one(
                    name=self.secondary_qos_policy,
                    fail_if_missing=True,
                ).id
            volume_data = dict(
                name=source_volume.name,
                view_id=secondary_subsystem.id,
                size=source_volume.size,
            )
            if qos_policy_id:
                volume_data["qos_policy_id"] = qos_policy_id
            self.secondary_vms_session.volumes.ensure(**volume_data)

        elif role.is_destination() and not create_volume:
            logger.info(f"Skipping volume creation (subsystem level replication)")

        return ppath, created
