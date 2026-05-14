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
VAST CSI-Addons Volume Group Plugin

Implements CSI-Addons Volume Group for NFS and Block (NVMe-oF) volumes.
Follows the CSI-Addons volume group specification.
https://github.com/csi-addons/spec/tree/main/replication
"""
import os
from typing import NamedTuple, Optional
from vast_csi.proto import volumegroup_pb2_grpc
from vast_csi.logging import logger
from vast_csi.lru_cache import VolumeGroupValidationCache
from vast_csi.plugins.base import Instrumented, AddonsIdentity
from vast_csi import csi_types as types
from vast_csi.exceptions import Abort
from vast_csi.filesystem_utils import resource_locked

CONF = None

# Compact suffix appended to every encoded volume group ID.
ID_SUFFIX_LENGTH = 10

# VolumeReplicationClass / VolumeGroupReplicationClass parameter key for the
# protected path name.  Written by the extensions-controller operator.
REPLICATION_PARAM_PPATH_NAME = "vastdata.com/ppath-name"
# VolumeReplicationClass / VolumeGroupReplicationClass parameter keys.
# These are written by the extensions-controller into the VRC parameters.
REPLICATION_PARAM_STORAGE_CLASS = "vastdata.com/storage-class"


class VolumeGroupMetadata(NamedTuple):
    """
    Parsed metadata from an encoded volume group ID.

    Attributes:
        suffix:     Volume group suffix (e.g., '9dc74656c').
        ppath_name: VAST protected path name created by the operator.
                    Used by the replication plugin to look up the ppath
                    without requiring extra parameters.
    """

    suffix: str
    ppath_name: Optional[str] = None


def _encode_volume_group_id(volume_group_id, ppath_name):
    """
    Encode a volume group ID with its operator-assigned ppath name.

    Format: ``{suffix}@n={ppath_name}``

    Example:
        >>> _encode_volume_group_id("vgrcontent-c509dc74656c", "app-replication")
        '9dc74656c@n=app-replication'
    """
    if not ppath_name:
        raise Abort(
            types.INVALID_ARGUMENT,
            f"Cannot encode volume group ID without a protected path name. "
            f"Ensure {REPLICATION_PARAM_PPATH_NAME!r} is set in the "
            f"VolumeGroupReplicationClass parameters.",
        )
    suffix = volume_group_id[-ID_SUFFIX_LENGTH:]
    return f"{suffix}@n={ppath_name}"


def _parse_volume_group_id(encoded_id) -> VolumeGroupMetadata:
    """
    Parse an encoded volume group ID to extract metadata.

    Format: ``{suffix}@n={ppath_name}``

    Falls back to defaults (``ppath_name=""``) when the ID pre-dates the
    ``@``-encoded format or when the ``n`` key is absent, so that callers can
    handle the missing ppath gracefully rather than receiving an hard error.

    Example:
        >>> _parse_volume_group_id("9dc74656c@n=app-replication")
        VolumeGroupMetadata(suffix='9dc74656c', ppath_name='app-replication')
        >>> _parse_volume_group_id("9dc74656c")
        VolumeGroupMetadata(suffix='9dc74656c', ppath_name='')
    """
    if "@" not in encoded_id:
        return VolumeGroupMetadata(suffix=encoded_id, ppath_name="")

    suffix, params_str = encoded_id.split("@", 1)

    params = {}
    for part in params_str.split(":"):
        if "=" in part:
            key, value = part.split("=", 1)
            params[key] = value

    ppath_name = params.get("n", "")

    return VolumeGroupMetadata(suffix=suffix, ppath_name=ppath_name)


################################################################
#
# Base Volume Group Controller
#
################################################################


class BaseVolumeGroupController(volumegroup_pb2_grpc.ControllerServicer):
    """Base class for CSI-Addons Volume Group Controllers."""

    # Subclasses must override these
    log_prefix = None

    # Shared validation cache across all instances
    _validation_cache = VolumeGroupValidationCache(maxsize=100)

    def __init__(self, config):
        self.config = config

    def CreateVolumeGroup(
        self,
        vms_session,
        exit_stack,
        name,
        parameters=None,
        volume_ids=None,
    ):
        """
        Create a new volume group.

        Args:
            vms_session: VAST API session (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            name: Name for the volume group (required for idempotency)
            parameters: Optional parameters for volume group creation
            volume_ids: Optional list of volume IDs to add to the group

        Returns:
            CreateVolumeGroupResponse with the created volume group
        """
        params = dict(parameters) if parameters else {}
        volume_ids = list(volume_ids) if volume_ids else []
        
        # Normalize volume IDs at entry point to handle any format from external callers
        # This ensures consistent volume lookups regardless of whether IDs have leading slashes
        normalized_volume_ids = [os.path.basename(vol_id) for vol_id in volume_ids]

        exit_stack.enter_context(resource_locked(name))

        # Implementation-specific creation logic
        volume_group = self._create_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=name,
            parameters=params,
            volume_ids=normalized_volume_ids,
        )

        return types.CreateVolumeGroupResp(volume_group=volume_group)

    def _create_volume_group_impl(
        self, vms_session, volume_group_id, parameters, volume_ids
    ):
        """
        Implementation-specific volume group creation logic.

        Override in subclasses to implement NFS or Block specific logic.

        Returns:
            VolumeGroup protobuf message
        """
        raise NotImplementedError("Subclasses must implement _create_volume_group_impl")

    def ModifyVolumeGroupMembership(
        self,
        vms_session,
        exit_stack,
        volume_group_id,
        volume_ids=None,
        parameters=None,
    ):
        """
        Modify the membership of a volume group.

        Args:
            vms_session: VAST API session (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            volume_group_id: ID of the volume group to modify
            volume_ids: New list of volume IDs (replaces existing membership)
            parameters: Optional parameters for modification

        Returns:
            ModifyVolumeGroupMembershipResponse with the updated volume group
        """
        params = dict(parameters) if parameters else {}
        volume_ids = list(volume_ids) if volume_ids else []
        
        # Normalize volume IDs at entry point to handle any format from external callers
        # This prevents endless cycles where caller sends /pvc-xxx, we return pvc-xxx,
        # but caller constructs new request with /pvc-xxx from another source
        normalized_volume_ids = [os.path.basename(vol_id) for vol_id in volume_ids]

        # Implementation-specific modification logic
        volume_group = self._modify_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=volume_group_id,
            volume_ids=normalized_volume_ids,
            parameters=params,
        )

        return types.ModifyVolumeGroupMembershipResp(volume_group=volume_group)

    def _modify_volume_group_impl(
        self, vms_session, volume_group_id, volume_ids, parameters
    ):
        """
        Implementation-specific volume group modification logic.

        Override in subclasses to implement NFS or Block specific logic.

        Returns:
            VolumeGroup protobuf message
        """
        raise NotImplementedError("Subclasses must implement _modify_volume_group_impl")

    def DeleteVolumeGroup(
        self,
        vms_session,
        exit_stack,
        volume_group_id,
    ):
        """
        Delete a volume group.

        Args:
            vms_session: VAST API session (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            volume_group_id: ID of the volume group to delete

        Returns:
            DeleteVolumeGroupResponse (empty on success)
        """
        exit_stack.enter_context(resource_locked(volume_group_id))

        # Implementation-specific deletion logic
        self._delete_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=volume_group_id,
        )

        return types.DeleteVolumeGroupResp()

    def _delete_volume_group_impl(self, vms_session, volume_group_id):
        """
        Implementation-specific volume group deletion logic.

        Override in subclasses to implement NFS or Block specific logic.
        """
        raise NotImplementedError("Subclasses must implement _delete_volume_group_impl")

    def ControllerGetVolumeGroup(
        self,
        vms_session,
        exit_stack,
        volume_group_id,
    ):
        """
        Get information about a volume group.

        Args:
            vms_session: VAST API session (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            volume_group_id: ID of the volume group to retrieve

        Returns:
            ControllerGetVolumeGroupResponse with volume group information
        """
        exit_stack.enter_context(resource_locked(volume_group_id))

        logger.info(f"{self.log_prefix}: Getting volume group '{volume_group_id}'")

        # Implementation-specific get logic
        volume_group = self._get_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=volume_group_id,
        )

        logger.info(f"{self.log_prefix}: Retrieved volume group '{volume_group_id}'")

        return types.ControllerGetVolumeGroupResp(volume_group=volume_group)

    def _get_volume_group_impl(self, vms_session, volume_group_id):
        """
        Implementation-specific volume group get logic.

        Override in subclasses to implement NFS or Block specific logic.

        Returns:
            VolumeGroup protobuf message
        """
        raise NotImplementedError("Subclasses must implement _get_volume_group_impl")

    def ListVolumeGroups(
        self,
        vms_session,
        exit_stack,
        max_entries=None,
        starting_token=None,
    ):
        """
        List volume groups.

        Args:
            vms_session: VAST API session (auto-injected)
            exit_stack: Context manager stack for resource cleanup
            max_entries: Optional maximum number of entries to return
            starting_token: Optional pagination token

        Returns:
            ListVolumeGroupsResponse with volume groups and pagination token
        """
        logger.info(
            f"{self.log_prefix}: Listing volume groups (max_entries={max_entries})"
        )

        # Implementation-specific list logic
        entries, next_token = self._list_volume_groups_impl(
            vms_session=vms_session,
            max_entries=max_entries,
            starting_token=starting_token,
        )

        logger.info(f"{self.log_prefix}: Found {len(entries)} volume groups")

        return types.ListVolumeGroupsResp(
            entries=entries,
            next_token=next_token or "",
        )

    def _list_volume_groups_impl(self, vms_session, max_entries, starting_token):
        """
        Implementation-specific volume group list logic.

        Override in subclasses to implement NFS or Block specific logic.

        Returns:
            Tuple of (list of VolumeGroup, next_token or None)
        """
        # Default implementation returns empty list
        return [], None


################################################################
#
# NFS Volume Group Controller
#
################################################################


class NFSVolumeGroupController(BaseVolumeGroupController, Instrumented):
    """CSI-Addons Volume Group Controller for NFS volumes."""

    log_prefix = "NFS"

    def _validate_volume_group_membership(self, vms_session, volume_ids, base_dir):
        """
        Validate that all volumes exist in the specified base directory.

        Args:
            vms_session: VAST API session
            volume_ids: List of volume IDs to validate
            base_dir: Base directory to validate against

        Raises:
            Abort: If any requested volumes are missing
        """
        # List all views in the base directory
        views_by_base_dir = vms_session.views.list(
            path__startswith=base_dir, fields="path"
        )
        ids_by_base_dir = {os.path.basename(view["path"]) for view in views_by_base_dir}

        # All requested volumes MUST exist in the base directory
        # Normalize volume_ids using basename to handle paths with leading slashes or subdirectories
        requested_ids = {os.path.basename(vol_id) for vol_id in volume_ids}
        missing_volumes = requested_ids - ids_by_base_dir

        if missing_volumes:
            raise Abort(
                types.NOT_FOUND,
                f"{len(missing_volumes)} volume(s) not found in {base_dir}: {', '.join(sorted(missing_volumes))}",
            )

        # Extra volumes are allowed but logged as a warning
        extra_volumes = ids_by_base_dir - requested_ids
        if extra_volumes:
            logger.warning(
                f"{len(extra_volumes)} extra volume(s) found in {base_dir} "
                f"(not part of the volume group):"
            )
            for vol_id in sorted(extra_volumes):
                logger.warning(f"  - {vol_id}")

    def _create_volume_group_impl(
        self, vms_session, volume_group_id, parameters, volume_ids
    ):
        """Create NFS volume group implementation."""
        ppath_name = parameters.get(REPLICATION_PARAM_PPATH_NAME)
        vms_session.protectedpaths.one(name=ppath_name, fail_if_missing=True)

        all_volumes = [types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids]

        return types.VolumeGroup(
            volume_group_id=_encode_volume_group_id(volume_group_id, ppath_name=ppath_name),
            volume_group_context={"type": self.log_prefix},
            volumes=all_volumes,
        )

    def _modify_volume_group_impl(
        self, vms_session, volume_group_id, volume_ids, parameters
    ):
        """
        Modify NFS volume group membership.

        Validates that all provided volumes exist in the volume group's base directory
        (derived from the protected path's source_dir).  Uses a cache to skip
        validation when all volumes were recently validated.
        """
        if not volume_ids:
            all_volumes = []
        else:
            normalized_volume_ids = [os.path.basename(vol_id) for vol_id in volume_ids]

            if self._validation_cache.are_all_validated(volume_group_id, normalized_volume_ids):
                logger.debug(
                    f"{self.log_prefix}: All {len(volume_ids)} volumes already validated "
                    f"for {volume_group_id}, skipping validation"
                )
            else:
                parsed = _parse_volume_group_id(volume_group_id)
                ppath = vms_session.protectedpaths.one(
                    name=parsed.ppath_name, fail_if_missing=True
                )
                base_dir = ppath.source_dir

                self._validate_volume_group_membership(vms_session, volume_ids, base_dir)
                self._validation_cache.add_validated(volume_group_id, normalized_volume_ids)

            all_volumes = [
                types.VolumeGroupVolume(volume_id=vol_id) for vol_id in normalized_volume_ids
            ]

        return types.VolumeGroup(
            volume_group_id=volume_group_id,
            volume_group_context={"type": self.log_prefix},
            volumes=all_volumes,
        )

    def _delete_volume_group_impl(self, vms_session, volume_group_id):
        """Delete NFS volume group."""
        # The actual volumes are not deleted, only the grouping
        logger.debug(
            f"{self.log_prefix}: Cleaning up volume group metadata for {volume_group_id}"
        )

    def _get_volume_group_impl(self, vms_session, volume_group_id):
        """
        Get NFS volume group information.

        Resolves the base directory from the protected path's source_dir and
        lists all member views beneath it.
        """
        parsed = _parse_volume_group_id(volume_group_id)

        ppath = vms_session.protectedpaths.one(name=parsed.ppath_name, fail_if_missing=True)
        base_dir = ppath.source_dir

        logger.debug(
            f"{self.log_prefix}: Getting volume group {parsed.suffix!r} "
            f"from ppath {parsed.ppath_name!r} (base_dir={base_dir!r})"
        )

        views = vms_session.views.list(path__startswith=base_dir, fields="path")
        member_volumes = [
            types.VolumeGroupVolume(volume_id=os.path.basename(v["path"])) for v in views
        ]

        logger.debug(f"{self.log_prefix}: has {len(member_volumes)} member(s)")

        return types.VolumeGroup(
            volume_group_id=volume_group_id,
            volume_group_context={"type": self.log_prefix},
            volumes=member_volumes,
        )


################################################################
#
# Block Volume Group Controller
#
################################################################


class BlockVolumeGroupController(BaseVolumeGroupController, Instrumented):
    """CSI-Addons Volume Group Controller for Block/NVMe-oF volumes."""

    log_prefix = "BLOCK"

    def _find_subsystem_for_source_dir(self, vms_session, source_dir):
        """
        Return the NVMe subsystem (a VAST view) whose path is a prefix of source_dir.

        The operator always sets source_dir to ``{subsystem.path}/{volumeGroup}``,
        so walking up one directory level is normally sufficient.  We continue
        upward to handle deeper subsystem paths.
        """
        path = os.path.dirname(source_dir)
        while path and path != "/":
            sub = vms_session.views.one(path=path, fail_if_missing=False)
            if sub:
                return sub
            path = os.path.dirname(path)
        raise Abort(
            types.NOT_FOUND,
            f"No NVMe subsystem found covering source_dir {source_dir!r}",
        )

    def _validate_volume_group_membership(self, *args, **kwargs):
        pass

    def _create_volume_group_impl(
        self, vms_session, volume_group_id, parameters, volume_ids
    ):
        """Create Block volume group implementation."""
        ppath_name = parameters.get(REPLICATION_PARAM_PPATH_NAME)
        vms_session.protectedpaths.one(name=ppath_name, fail_if_missing=True)

        all_volumes = [types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids]

        return types.VolumeGroup(
            volume_group_id=_encode_volume_group_id(volume_group_id, ppath_name=ppath_name),
            volume_group_context={"type": self.log_prefix},
            volumes=all_volumes,
        )

    def _modify_volume_group_impl(
        self, vms_session, volume_group_id, volume_ids, parameters
    ):
        """
        Modify Block volume group membership.

        Validates that all provided volumes exist in the subsystem/prefix derived
        from the protected path's source_dir.  Uses a cache to skip validation when
        all volumes were recently validated.
        """
        if not volume_ids:
            all_volumes = []
        else:
            normalized_volume_ids = [os.path.basename(vol_id) for vol_id in volume_ids]

            if self._validation_cache.are_all_validated(volume_group_id, normalized_volume_ids):
                logger.info(
                    f"{self.log_prefix}: All {len(volume_ids)} volumes already validated "
                    f"for {volume_group_id}, skipping validation"
                )
            else:
                parsed = _parse_volume_group_id(volume_group_id)
                ppath = vms_session.protectedpaths.one(
                    name=parsed.ppath_name, fail_if_missing=True
                )
                source_dir = ppath.source_dir

                self._validate_volume_group_membership(
                    vms_session, volume_ids, source_dir
                )
                self._validation_cache.add_validated(volume_group_id, normalized_volume_ids)

            all_volumes = [
                types.VolumeGroupVolume(volume_id=vol_id) for vol_id in normalized_volume_ids
            ]

        return types.VolumeGroup(
            volume_group_id=volume_group_id,
            volume_group_context={"type": self.log_prefix},
            volumes=all_volumes,
        )

    def _delete_volume_group_impl(self, vms_session, volume_group_id):
        """Delete Block volume group."""
        # For Block, cleanup any metadata associated with the group
        # The actual volumes are not deleted, only the grouping
        logger.debug(
            f"{self.log_prefix}: Cleaning up volume group metadata for {volume_group_id}"
        )

    def _get_volume_group_impl(self, vms_session, volume_group_id):
        """
        Get Block volume group information.

        Resolves the subsystem and base directory from the protected path's
        source_dir, then retrieves all member volumes.
        """
        parsed = _parse_volume_group_id(volume_group_id)

        ppath = vms_session.protectedpaths.one(name=parsed.ppath_name, fail_if_missing=True)
        source_dir = ppath.source_dir

        logger.debug(
            f"{self.log_prefix}: Getting volume group {parsed.suffix!r} "
            f"from ppath {parsed.ppath_name!r} (source_dir={source_dir!r})"
        )

        subsystem = self._find_subsystem_for_source_dir(vms_session, source_dir)

        rel = source_dir[len(subsystem.path):].lstrip("/")
        base_prefix = rel or None

        logger.debug(
            f"{self.log_prefix}: subsystem={subsystem.path!r}, prefix={base_prefix!r}"
        )

        kwargs = dict(subsystem_name=subsystem.name, fields="name")
        if base_prefix:
            kwargs["name__contains"] = base_prefix

        volumes = vms_session.volumes.list(**kwargs)
        member_volumes = [
            types.VolumeGroupVolume(volume_id=os.path.basename(v["name"])) for v in volumes
        ]

        return types.VolumeGroup(
            volume_group_id=volume_group_id,
            volume_group_context={"type": self.log_prefix},
            volumes=member_volumes,
        )


################################################################
#
# Serve Function
#
################################################################


def serve(server, conf, plugin: str):
    """
    Serve function for the CSI-Addons volume group plugin.

    This is called when the driver is started with --addons volumegroup[nfs] or volumegroup[block].
    It registers the appropriate volume group controller on the provided gRPC server.

    Args:
        server: gRPC server to register services on
        conf: Configuration object
        plugin: Plugin name (e.g., "volumegroup[nfs]" or "volumegroup[block]")
    """
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf

    plugin_type = "NFS" if plugin == "volumegroup[nfs]" else "Block"
    logger.info(f"Starting CSI-Addons {plugin_type} Volume Group Plugin")

    # Add volume group capabilities to the shared identity
    AddonsIdentity.add_volume_group_capabilities()
    AddonsIdentity.register(server)

    # Register the appropriate Volume Group Controller based on plugin type
    if plugin == "volumegroup[nfs]":
        volumegroup_controller = NFSVolumeGroupController(conf)
    else:  # volumegroup[block]
        volumegroup_controller = BlockVolumeGroupController(conf)

    volumegroup_pb2_grpc.add_ControllerServicer_to_server(
        volumegroup_controller, server
    )
    logger.info(f"{plugin_type} Volume Group Controller service registered")
