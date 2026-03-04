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

# Volume group ID encoding configuration
# This keeps the ID compact while preserving the base directory path
ID_SUFFIX_LENGTH = 10


class VolumeGroupMetadata(NamedTuple):
    """
    Parsed metadata from an encoded volume group ID.

    Attributes:
        suffix: Volume group suffix including 'vg-' prefix (e.g., 'vg-9dc74656c')
        tenant_name: Tenant name (e.g., 'default')
        path: Path component:
            - For NFS: Full base directory path (e.g., '/k8s/myapp')
            - For Block: Volume prefix or '/' if no prefix (e.g., 'base' or '/')
        subsystem_name: Subsystem name (Block only, e.g., 'nvmeof'), None for NFS
    """

    suffix: str
    tenant_name: str
    path: str
    subsystem_name: Optional[str] = None


def _encode_volume_group_id(volume_group_id, tenant_name, path, subsystem_name=None):
    """
    Encode a volume group ID with metadata using key-value pairs.

    Args:
        volume_group_id: Full volume group ID (e.g., "vgrcontent-9b54846c-dcc5-4238-9c8a-c509dc74656c")
        tenant_name: Tenant name (e.g., "default")
        path: Path component:
            - For NFS: Full base directory path (e.g., "/k8s/myapp")
            - For Block: Volume prefix or "/" if no prefix (e.g., "base" or "/")
        subsystem_name: Subsystem name (Block only, e.g., "nvmeof")

    Returns:
        Encoded ID in format: {suffix}@t={tenant}:p={path}[:s={subsystem}]

    Examples:
        >>> _encode_volume_group_id("vgrcontent-c509dc74656c", "default", "/k8s/myapp")
        '9dc74656c@t=default:p=/k8s/myapp'
        >>> _encode_volume_group_id("vgrcontent-c509dc74656c", "default", "base", "nvmeof")
        '9dc74656c@t=default:p=base:s=nvmeof'
        >>> _encode_volume_group_id("vgrcontent-c509dc74656c", "default", "/", "nvmeof")
        '9dc74656c@t=default:p=/:s=nvmeof'
    """
    suffix = volume_group_id[-ID_SUFFIX_LENGTH:]

    # Build key-value pairs with single-letter abbreviations:
    # t=tenant, p=path, s=subsystem
    params = [
        f"t={tenant_name}",
        f"p={path}",
    ]

    if subsystem_name:
        params.append(f"s={subsystem_name}")

    params_str = ":".join(params)
    return f"{suffix}@{params_str}"


def _parse_volume_group_id(encoded_id) -> VolumeGroupMetadata:
    """
    Parse an encoded volume group ID to extract metadata.

    Args:
        encoded_id: Encoded ID in format: {suffix}@t={tenant}:p={path}[:s={subsystem}]

    Returns:
        VolumeGroupMetadata with parsed fields

    Examples:
        >>> _parse_volume_group_id("9dc74656c@t=default:p=/k8s/myapp")
        VolumeGroupMetadata(suffix='9dc74656c', tenant_name='default', path='/k8s/myapp', subsystem_name=None)
        >>> _parse_volume_group_id("9dc74656c@t=default:p=base:s=nvmeof")
        VolumeGroupMetadata(suffix='9dc74656c', tenant_name='default', path='base', subsystem_name='nvmeof')
    """
    if "@" not in encoded_id:
        raise ValueError(
            f"Invalid encoded volume group ID format: {encoded_id}. "
            f"Expected format: {{suffix}}@t={{tenant}}:p={{path}}[:s={{subsystem}}]"
        )

    suffix, params_str = encoded_id.split("@", 1)

    # Parse key-value pairs (separated by colon)
    # Single-letter keys: t=tenant, p=path, s=subsystem
    params = {}
    for param in params_str.split(":"):
        if "=" in param:
            key, value = param.split("=", 1)
            params[key] = value

    # Validate required fields
    if "t" not in params:
        raise ValueError(
            f"Missing required 't' (tenant_name) in volume group ID: {encoded_id}"
        )
    if "p" not in params:
        raise ValueError(
            f"Missing required 'p' (path) in volume group ID: {encoded_id}"
        )

    return VolumeGroupMetadata(
        suffix=suffix,
        tenant_name=params["t"],
        path=params["p"],
        subsystem_name=params.get("s"),
    )


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

        exit_stack.enter_context(resource_locked(name))

        # Implementation-specific creation logic
        volume_group = self._create_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=name,
            parameters=params,
            volume_ids=volume_ids,
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

        # Implementation-specific modification logic
        volume_group = self._modify_volume_group_impl(
            vms_session=vms_session,
            volume_group_id=volume_group_id,
            volume_ids=volume_ids,
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

    def _get_volume_group_base_directory(self, vms_session, first_view):
        """
        Get the base directory for a volume group from the first view.

        Args:
            vms_session: VAST API session
            first_view: The first view in the volume group

        Returns:
            str: The base directory path
        """
        base_dir = os.path.dirname(first_view.path)
        logger.info(f"{self.log_prefix}: Volume group base directory: {base_dir!r}")
        return base_dir

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
        requested_ids = set(volume_ids)
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

        volume_group_context = {"type": self.log_prefix}

        if not volume_ids:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"Cannot create empty volume group. At least one volume required.",
            )

        # Get tenant name from the first volume's view
        first_volume_id = volume_ids[0]
        first_view = vms_session.views.one(
            path__contains=first_volume_id, fail_if_missing=True
        )

        # Get base directory from first view
        base_dir = self._get_volume_group_base_directory(vms_session, first_view)
        tenant_name = first_view.tenant_name

        # Build Volume objects for all validated volumes
        all_volumes = [
            types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids
        ]

        # Embed metadata in volume_group_id
        volume_group_id_with_path = _encode_volume_group_id(
            volume_group_id, tenant_name=tenant_name, path=base_dir
        )

        return types.VolumeGroup(
            volume_group_id=volume_group_id_with_path,
            volume_group_context=volume_group_context,
            volumes=all_volumes,
        )

    def _modify_volume_group_impl(
        self, vms_session, volume_group_id, volume_ids, parameters
    ):
        """
        Modify NFS volume group membership.

        Validates that all provided volumes exist in the volume group's base directory.
        Uses cache to skip validation if all volumes were recently validated.
        Returns the volume group with provided volume_ids.
        """
        if not volume_ids:
            all_volumes = []
        else:
            # Check cache first - skip validation if all volumes are already validated
            if self._validation_cache.are_all_validated(volume_group_id, volume_ids):
                logger.debug(
                    f"{self.log_prefix}: All {len(volume_ids)} volumes already validated for {volume_group_id}, "
                    f"skipping validation"
                )
            else:
                # Parse metadata to get the base directory
                parsed = _parse_volume_group_id(volume_group_id)
                base_dir = parsed.path

                # Validate all volumes exist in the base directory
                self._validate_volume_group_membership(vms_session, volume_ids, base_dir)

                # Add validated volumes to cache
                self._validation_cache.add_validated(volume_group_id, volume_ids)

            # Build Volume objects for the validated volume IDs
            all_volumes = [
                types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids
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

        Parses the volume_group_id to extract metadata and
        retrieves all member volumes from that directory.
        """

        parsed = _parse_volume_group_id(volume_group_id)
        base_dir = parsed.path
        logger.debug(
            f"{self.log_prefix}: Getting volume group {parsed.suffix} from base directory: {base_dir}"
        )

        # Query all views in the base directory
        views = vms_session.views.list(path__startswith=base_dir, fields="path")

        # Extract volume IDs from view paths
        member_volumes = []
        for view in views:
            volume_id = os.path.basename(view["path"])
            member_volumes.append(types.VolumeGroupVolume(volume_id=volume_id))

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

    def _get_volume_group_base_directory(self, vms_session, first_volume):
        """
        Get the base directory (subsystem path + prefix) for a volume group from the first volume.

        Args:
            vms_session: VAST API session
            first_volume: The first volume in the volume group

        Returns:
            str: The base directory path (subsystem_path/base_prefix or subsystem_path)
        """
        # Get the subsystem for the first volume
        subsystem = vms_session.views.get_subsystem_by_id(_id=first_volume.view_id)
        if not subsystem:
            raise Abort(types.NOT_FOUND, f"Unknown subsystem: {first_volume.view_id}")

        subsystem_path = subsystem.path

        # Check if first volume has a base prefix (e.g., "base/pvc-xxxxx")
        name_parts = first_volume.name.split("/")
        if len(name_parts) > 1:
            # Take all parts except the last one (which is the volume ID)
            # e.g., "dev/mapper/pvc-xxx" -> "dev/mapper"
            base_prefix = "/".join(name_parts[:-1])
            logger.info(
                f"Volume group base directory: {subsystem_path}/{base_prefix}. "
                "It is a subsystem sub directory level group."
            )
            return os.path.join(subsystem_path, base_prefix)
        else:
            logger.info(
                f"Volume group base directory: {subsystem_path}. "
                f"It is subsystem root level group."
            )
            return subsystem_path

    def _validate_volume_group_membership(
        self, vms_session, volume_ids, subsystem, path
    ):
        """
        Validate that all volumes exist in the specified subsystem with optional prefix.

        Args:
            vms_session: VAST API session
            volume_ids: List of volume IDs to validate
            subsystem: subsystem object
            path: Path component (prefix or "/" if no prefix)

        Raises:
            Abort: If any requested volumes are missing
        """
        # Get subsystem by name

        subsystem_path = subsystem.path
        base_prefix = None if path == "/" else path

        kwargs = dict(
            subsystem_name=subsystem.name,
            fields="name",
        )

        if base_prefix:
            kwargs["name__contains"] = base_prefix

        volumes_in_subsystem = vms_session.volumes.list(**kwargs)

        # Extract volume IDs from the full names
        ids_in_subsystem = {
            os.path.basename(vol["name"]) for vol in volumes_in_subsystem
        }

        # All requested volumes MUST exist in the subsystem
        requested_ids = set(volume_ids)
        missing_volumes = requested_ids - ids_in_subsystem

        if missing_volumes:
            location = (
                f"{subsystem_path}/{base_prefix}" if base_prefix else subsystem_path
            )
            raise Abort(
                types.NOT_FOUND,
                f"{len(missing_volumes)} volume(s) not found in {location}: {', '.join(sorted(missing_volumes))}",
            )

        # Extra volumes are allowed but logged as a warning
        extra_volumes = ids_in_subsystem - requested_ids
        if extra_volumes:
            location = (
                f"{subsystem_path}/{base_prefix}" if base_prefix else subsystem_path
            )
            logger.warning(
                f"{len(extra_volumes)} extra volume(s) found in {location} "
                f"(not part of the volume group):"
            )
            for vol_id in sorted(extra_volumes):
                logger.warning(f"  - {vol_id}")

    def _create_volume_group_impl(
        self, vms_session, volume_group_id, parameters, volume_ids
    ):
        """
        Create Block volume group implementation.

        Returns a VolumeGroup with volume_group_id in format: {group_id}@{base_dir}
        """
        volume_group_context = {"type": self.log_prefix}

        if not volume_ids:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"Cannot create empty volume group. At least one volume required.",
            )

        # Get subsystem and tenant information from the first volume
        first_volume_id = volume_ids[0]
        first_volume = vms_session.volumes.one(
            name__contains=first_volume_id,
            fail_if_missing=True,
        )

        # Get base directory from first volume
        base_dir = self._get_volume_group_base_directory(vms_session, first_volume)
        subsystem = vms_session.views.get_subsystem_by_id(_id=first_volume.view_id)

        # Determine path component (prefix or "/" if no prefix)
        # base_dir is either subsystem.path or subsystem.path/prefix
        if base_dir == subsystem.path:
            path = "/"
        else:
            # Extract prefix part
            path = base_dir[len(subsystem.path) :].lstrip("/")

        self._validate_volume_group_membership(
            vms_session, volume_ids, subsystem, path,
        )

        # Build Volume objects for all validated volumes
        all_volumes = [
            types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids
        ]

        # Embed metadata in volume_group_id
        volume_group_id_with_path = _encode_volume_group_id(
            volume_group_id,
            tenant_name=subsystem.tenant_name,
            path=path,
            subsystem_name=subsystem.name,
        )

        return types.VolumeGroup(
            volume_group_id=volume_group_id_with_path,
            volume_group_context=volume_group_context,
            volumes=all_volumes,
        )

    def _modify_volume_group_impl(
        self, vms_session, volume_group_id, volume_ids, parameters
    ):
        """
        Modify Block volume group membership.

        Validates that all provided volumes exist in the volume group's subsystem/prefix.
        Uses cache to skip validation if all volumes were recently validated.
        Returns the volume group with provided volume_ids.
        """
        if not volume_ids:
            all_volumes = []
        else:
            # Check cache first - skip validation if all volumes are already validated
            if self._validation_cache.are_all_validated(volume_group_id, volume_ids):
                logger.info(
                    f"{self.log_prefix}: All {len(volume_ids)} volumes already validated for {volume_group_id}, "
                    f"skipping validation"
                )
            else:
                # Parse metadata to get subsystem and path
                parsed = _parse_volume_group_id(volume_group_id)
                subsystem_name = parsed.subsystem_name
                path = parsed.path

                subsystem = vms_session.views.get_subsystem(subsystem=subsystem_name)
                if not subsystem:
                    raise Abort(types.NOT_FOUND, f"Unknown subsystem: {subsystem_name}")

                # Validate all volumes exist in the subsystem/prefix
                self._validate_volume_group_membership(
                    vms_session, volume_ids, subsystem, path
                )

                # Add validated volumes to cache
                self._validation_cache.add_validated(volume_group_id, volume_ids)

            # Build Volume objects for the validated volume IDs
            all_volumes = [
                types.VolumeGroupVolume(volume_id=vol_id) for vol_id in volume_ids
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

        Parses the volume_group_id to extract the base directory and
        retrieves all member volumes from that subsystem/prefix.
        """

        # Parse metadata from volume_group_id
        parsed = _parse_volume_group_id(volume_group_id)

        subsystem_name = parsed.subsystem_name
        path = parsed.path

        logger.debug(
            f"{self.log_prefix}: Getting volume group {parsed.suffix} "
            f"from subsystem '{subsystem_name}' with path '{path}'"
        )

        subsystem = vms_session.views.get_subsystem(subsystem=subsystem_name)
        if not subsystem:
            raise ValueError(f"Unknown subsystem: {subsystem_name}")

        # Determine if there's a prefix
        base_prefix = None if path == "/" else path

        logger.info(
            f"{self.log_prefix}: Subsystem path: {subsystem.path}, "
            f"prefix: {base_prefix}"
        )

        kwargs = dict(
            subsystem_name=subsystem.name,
            fields="name",
        )
        if base_prefix:
            kwargs["name__contains"] = base_prefix

        volumes = vms_session.volumes.list(**kwargs)

        # Extract volume IDs from volume names
        member_volumes = []
        for vol in volumes:
            volume_id = os.path.basename(vol["name"])
            member_volumes.append(types.VolumeGroupVolume(volume_id=volume_id))

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
