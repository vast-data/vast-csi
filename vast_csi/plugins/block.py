# Copyright 2024 VAST Data Inc.
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
import os.path
from contextlib import contextmanager, nullcontext
from tempfile import TemporaryDirectory

from plumbum import local, cmd, ProcessExecutionError
from plumbum.commands.processes import ProcessTimedOut
import grpc

from easypy.timing import timing
from easypy.tokens import CONTROLLER_AND_NODE, CONTROLLER, NODE
from easypy.caching import cached_property

from vast_csi.logging import logger
from vast_csi.proto import csi_pb2_grpc as csi_grpc
from vast_csi import csi_types as types
from vast_csi.csi_types import (
    INVALID_ARGUMENT,
    ALREADY_EXISTS,
    NOT_FOUND,
    FAILED_PRECONDITION,
)
from vast_csi.builders import (
    EmptyBlockVolumeBuilder,
    BlockVolumeFromVolumeBuilder,
    BlockVolumeFromSnapshotBuilder,
    StaticBlockVolumeBuilder,
    to_volume_id_with_metadata,
)
from vast_csi.exceptions import (
    Abort,
    VolumeAlreadyExists,
    SourceNotFound,
    MountFailed,
    NVMEConnectionFailed,
    UmountTimedOut,
)
from vast_csi.block_utils import (
    connect_nvme_targets,
    get_connected_session,
    get_nvme_device_by_nguid,
    try_nvme_probes,
    change_io_policy,
    disable_nvme_timeout,
    is_native_multipath_enabled,
)
from vast_csi.utils import (
    stringify_dict,
    string_to_proto_timestamp,
    get_random_fqdn_prefix,
    string_to_static_uuid,
)
from vast_csi.filesystem_utils import (
    get_filesystem_type,
    MountInfo,
    format_device,
    resize_device,
    get_device_size,
    check_fs_integrity,
    volume_locked,
    run_with_timeout,
)
from vast_csi.configuration import Config
import vast_csi.capabilities as cap_lib
from vast_csi.plugins.base import (
    IdentityBase,
    ControllerBase,
    NodeBase,
    Instrumented,
)


CONF = None
ServiceCapabilities = cap_lib.ServiceCapabilities(
    support_filesystem=True, support_block=True, can_many_rwx=True
)


################################################################
#
# Helpers
#
################################################################

def nvme_connect(host_nqn, discovery_server, host_id, subsystem_nqn, metrics_registry=None):
    """Connect to NVMe targets with auto-instrumented metrics."""

    if metrics_registry:
        metrics_manager = metrics_registry.nvme_connect()
    else:
        metrics_manager = nullcontext()

    try:
        with metrics_manager:
            return connect_nvme_targets(
                discovery_server=discovery_server,
                host_nqn=host_nqn,
                host_id=host_id,
                subsystem_nqn=subsystem_nqn,
            )
    except ProcessExecutionError as exc:
        raise NVMEConnectionFailed(detail=exc.stderr, host_nqn=host_nqn, discovery_server=discovery_server)


def mount(src, tgt, flags=None, bind=False, fs_type=None, metrics_registry=None):
    """
    Mount block device with auto-instrumented metrics.
    
    Args:
        src (str): The source path to be mounted (e.g., a device or directory).
        tgt (str): The target path where the source will be mounted.
        flags (list, optional): Additional mount options (e.g., 'ro', 'noexec') to be passed with the -o flag.
        bind (bool, optional): If True, the mount is performed as a bind mount using the --bind option.
        fs_type (str, optional): The filesystem type to be used for the mount (e.g., 'ext4', 'xfs').
        metrics_registry: Optional MetricsRegistry instance (injected by framework if metrics enabled)
    """
    if bind:
        executable = cmd.mount["--bind"]
    elif fs_type:
        executable = cmd.mount["-t", fs_type]
    else:
        executable = cmd.mount
    if flags:
        executable = executable["-o", ",".join(flags)]
    timeout = CONF.mount_umount_timeout
    flags_str = ",".join(flags) if flags else "(none)"
    mount_type = "bind" if bind else (f"fs_type={fs_type}" if fs_type else "default")
    logger.info(f"Mounting {src!r} -> {tgt!r} ({mount_type}) with flags: {flags_str}")
    
    if metrics_registry:
        metrics_manager = metrics_registry.mount("block_mount")
    else:
        metrics_manager = nullcontext()

    try:
        with (
            metrics_manager,
            timing() as timer,
        ):
            executable['-v', src, tgt].run(timeout=timeout)
    except ProcessTimedOut:
        raise MountFailed(detail=f"mount timed out after {timeout}s", src=src, tgt=tgt, mount_options=flags)
    except ProcessExecutionError as exc:
        raise MountFailed(detail=exc.stderr, src=src, tgt=tgt, mount_options=flags)
    
    logger.info(f"Mount succeeded in {timer.elapsed}: {src!r} -> {tgt!r}")


def umount(path, ignore_not_mounted=False, metrics_registry=None):
    """
    Unmount block device with auto-instrumented metrics.

    Args:
        path: Path to unmount
        ignore_not_mounted: If True, ignore "not mounted" errors
        metrics_registry: Optional MetricsRegistry instance
    
    Returns:
        True if unmounted, False if not mounted
    """
    timeout = CONF.mount_umount_timeout
    logger.info(f"Unmounting {path!r} with timeout: {timeout}s")

    def do_umount():
        return cmd.umount['-v', path].run()

    
    if metrics_registry:
        metrics_manager = metrics_registry.umount("block_mount")
    else:
        metrics_manager = nullcontext()

    try:
        with (
            metrics_manager,
            timing() as timer,
        ):
            if timeout:
                run_with_timeout(do_umount, timeout)
            else:
                do_umount()
    except (TimeoutError, ProcessTimedOut):
        raise UmountTimedOut(f"umount timed out after {timeout}s for path: {path}")
    except ProcessExecutionError as exc:
        if "not mounted" in exc.stderr:
            if ignore_not_mounted:
                logger.info(f"Umount: {path!r} is not mounted (ignored)")
                return False
            logger.warning(f"Umount failed - {path!r} is not mounted (race?)")
            return False
        raise

    logger.info(f"Umount succeeded in {timer.elapsed}: {path!r}")
    return True


@contextmanager
def temporary_mount(src, tgt_dir, fs_type):
    """
    Creates a temporary mount for the given source and target directory.
    Primary usage of this context manager is to resize
    the XFS filesystem because it requires the filesystem to be mounted.
    Note: attempts to resize XFS fs on source device lead to error:
     /dev/device is not a mounted XFS filesystem

    Args:
        src (str): The source path to be mounted (e.g., a device or directory).
        tgt_dir (str): The target directory where the source will be temporarily mounted.
        fs_type (str, optional): The filesystem type to be used for the mount (e.g., 'xfs').
    """
    # Create a temporary directory within the target directory
    with TemporaryDirectory(dir=tgt_dir) as temp_mount_point:
        bind = False if fs_type == "xfs" else True
        if bind:
            # Create tmp file for bind mount. It will be deleted on context exit.
            temp_mount_point = os.path.join(temp_mount_point, "device")
            open(temp_mount_point, "a").close()
        # Perform the mount
        mount(src=src, tgt=temp_mount_point, bind=bind, fs_type=fs_type)
        try:
            yield temp_mount_point
        finally:
            umount(temp_mount_point, ignore_not_mounted=True)


def umount_safe(path, metrics_registry=None):
    """Unmounts a path if it is mounted (legacy wrapper for umount)."""
    umount(path, ignore_not_mounted=True, metrics_registry=metrics_registry)

def remove_path_if_not_mounted(path):
    path = local.path(path)
    if MountInfo.get_mount_by_destination(
            dest_path=path, resolve_symlink=CONF.resolve_mount_symlinks,
    ):
        raise Exception(f"Path {path} is mounted. Cannot remove.")
    path.delete()


def _validate_capabilities(capabilities, volume_context=None, publish_context=None):
    try:
        return ServiceCapabilities.make_and_validate(capabilities, volume_context, publish_context)
    except cap_lib.CapValidationError as exc:
        raise Abort(INVALID_ARGUMENT, exc.render(color=False))


def get_device_bind_path(staging_target_path):
    """
    Common convention for bind-mounting block devices
    between source block device and staging path.
    """
    return local.path(staging_target_path)["device"]

################################################################
#
# Identity
#
################################################################


class BlockIdentity(IdentityBase, Instrumented):
    pass


################################################################
#
# Controller
#
################################################################

class BlockController(ControllerBase, Instrumented):
    CAPABILITIES = [
        types.CtrlCapabilityType.CREATE_DELETE_VOLUME,
        types.CtrlCapabilityType.PUBLISH_UNPUBLISH_VOLUME,
        types.CtrlCapabilityType.CREATE_DELETE_SNAPSHOT,
        types.CtrlCapabilityType.EXPAND_VOLUME,
        types.CtrlCapabilityType.CLONE_VOLUME,
    ]


    def ValidateVolumeCapabilities(
            self,
            vms_session,
            context,
            volume_id,
            volume_capabilities,
            volume_context=None,
            parameters=None,
    ):
        if not vms_session.views.one(name=volume_id):
            raise Abort(NOT_FOUND, f"Volume {volume_id} does not exist")
        try:
            _validate_capabilities(volume_capabilities, volume_context)
        except Abort as exc:
            return types.ValidateResp(message=exc.message)

        confirmed = types.ValidateResp.Confirmed(
            volume_context=volume_context,
            volume_capabilities=volume_capabilities,
            parameters=parameters,
        )

        return types.ValidateResp(confirmed=confirmed)

    def CreateVolume(
            self,
            vms_session,
            name,
            volume_capabilities,
            capacity_range=None,
            parameters=None,
            volume_content_source=None,
    ):
        volume_capabilities = _validate_capabilities(volume_capabilities)
        if volume_capabilities.is_filesystem and volume_capabilities.multi_mode:
            raise Abort(
                INVALID_ARGUMENT,
                "Filesystem volumes do not support multi-node attach."
            )
        parameters = parameters or dict()
        if not volume_content_source:
            builder_cls = EmptyBlockVolumeBuilder
        elif volume_content_source.snapshot.snapshot_id:
            builder_cls = BlockVolumeFromSnapshotBuilder
        elif volume_content_source.volume.volume_id:
            builder_cls = BlockVolumeFromVolumeBuilder
        try:
            volume = builder_cls.build(
                conf=CONF,
                vms_session=vms_session,
                name=name,
                volume_capabilities=volume_capabilities,
                capacity_range=capacity_range,
                parameters=parameters,
                volume_content_source=volume_content_source,
            )
        except SourceNotFound as exc:
            raise Abort(NOT_FOUND, exc.message)
        except VolumeAlreadyExists as exc:
            raise Abort(ALREADY_EXISTS, exc.message)
        return types.CreateResp(volume=volume)

    def DeleteVolume(self, vms_session, volume_id):
        vms_session.globalsnapstreams.ensure_snapshot_stream_deleted(name__contains=volume_id)
        if vms_session.snapshots.has_snapshots(volume_id):
            raise Exception(f"Unable to delete {volume_id} as it holds snapshots")
        # Unmap is occurring implicitly due to the use of the force flag.
        vms_session.volumes.delete(name__endswith=volume_id)
        return types.DeleteResp()

    def ControllerPublishVolume(
            self,
            vms_session,
            node_id,
            volume_id,
            volume_capability,
            exit_stack,
            volume_context=None,
    ):
        volume_context = volume_context or dict()
        volume_capabilities = _validate_capabilities(volume_capability, volume_context)
        if "volume_id" not in volume_context:
            # Assumed consuming existing volume where user specified full path to view in volumeHandle attribute.
            if volume_id != "/":
                # keep path consistent.
                volume_id = volume_id.rstrip("/")
            logger.info(f"Binding static volume: {volume_id}")
            try:
                volume_context = StaticBlockVolumeBuilder.build(
                    conf=CONF,
                    vms_session=vms_session,
                    name=volume_id,
                    volume_capabilities=volume_capabilities,
                    parameters=volume_context,
                )
            except SourceNotFound as exc:
                raise Abort(NOT_FOUND, exc.message)
        transport_type = volume_context["transport_type"]
        vol_id = int(volume_context["volume_id"])
        tenant_name = volume_context["tenant_name"]
        subsystem = volume_context["subsystem"]
        host_encryption = volume_context.get("host_encryption", False)

        if CONF.block_hosts_auto_prune:
            # Ensure map host operations are atomic based on the composite key (node ID + tenant name).
            exit_stack.enter_context(volume_locked(f"{node_id}:{tenant_name}"))
        blockhost = vms_session.blockhosts.ensure(
            node_id=f"{CONF.block_hosts_prefix}{node_id}",
            transport_type=transport_type,
            tenant_name=tenant_name,
            subsystem=subsystem,
        )
        vms_session.blockhostmappings.ensure_map(
            volume_id=vol_id,
            host_id=blockhost.id,
        )
        vip_pool_name = volume_context.get("vip_pool_name")
        vip_pool_fqdn = volume_context.get("vip_pool_fqdn")
        if vip_pool_fqdn:
            discovery_server = vip_pool_fqdn
            if volume_context.get("vip_pool_fqdn_random_prefix"):
                prefix = get_random_fqdn_prefix()
                discovery_server = f"{prefix}.{discovery_server}"
        elif vip_pool_name:
            discovery_server = vms_session.vippools.get_vip(vip_pool_name=vip_pool_name)
        else:
            discovery_server = CONF.use_local_ip_for_mount
            assert discovery_server, f"{discovery_server=}"
            logger.info(f"Using local IP for block: {discovery_server}")

        subsystem_nqn = volume_context["subsystem_nqn"]
        nguid = volume_context["nguid"]
        host_nqn = blockhost.nqn
        if not host_nqn.startswith(CONF.block_nqn_prefix):
            logger.warning(
                f"Host {host_nqn} is not CSI-managed (expected prefix: {CONF.block_nqn_prefix})"
            )
        publish_context = dict(
                subsystem_nqn=subsystem_nqn,
                host_nqn=blockhost.nqn,
                nguid=nguid,
                discovery_server=discovery_server,
            )

        if isinstance(host_encryption, dict):
            for k, v in host_encryption.items():
                publish_context[f"host_encryption.{k}"] = str(v)

        return types.CtrlPublishResp(publish_context=publish_context)

    def ControllerUnpublishVolume(
            self,
            vms_session,
            node_id,
            volume_id,
            exit_stack,
    ):
        """
        Unpublishes a volume from a node and checks if the host has any remaining volumes.
        If no volumes remain and the host was created by the CSI driver, the host is removed to prevent NQN sprawl.
        """
        # Early return if volume not found
        if not (volume := vms_session.volumes.one(name__endswith=volume_id)):
            logger.info(f"Volume not found with name: {volume_id}")
        else:
            block_host_name = f"{CONF.block_hosts_prefix}{node_id}"
            vms_session.blockhostmappings.ensure_unmap(
                volume__id=volume.id,
                block_host__name=block_host_name
            )
            if CONF.block_hosts_auto_prune:
                # Ensure get/delete host operations are atomic based on the composite key (node ID + tenant name).
                # A race condition may occur if ControllerUnpublishVolume unmaps the last volume from a host
                # while ControllerPublishVolume simultaneously maps a new volume to the same host.
                # In such cases, we must either delete and recreate the host, or wait for the new mapping and skip deletion.
                exit_stack.enter_context(volume_locked(f"{node_id}:{volume.tenant_name}"))
                if host := vms_session.blockhosts.one(name=block_host_name, tenant_name=volume.tenant_name):
                    if not host.mapped_volumes_preview and host.nqn.startswith(CONF.block_nqn_prefix):
                        logger.info(f"Host {block_host_name!r} has no remaining volumes, removing host")
                        vms_session.blockhosts.delete_by_id(host.id)

        return types.CtrlUnpublishResp()

    def ControllerExpandVolume(self, vms_session, volume_id, capacity_range):
        requested_capacity = capacity_range.required_bytes
        logger.debug(f"Requested capacity for volume {volume_id}: {requested_capacity} bytes")
        if not (volume := vms_session.volumes.one(name__endswith=volume_id)):
            raise Abort(NOT_FOUND, f"Volume not found with ID: {volume_id}")
        # Determine the current and new capacity
        existing_capacity = volume.size
        capacity_bytes = max(requested_capacity, existing_capacity)
        # Update the volume size only if expansion is needed
        if requested_capacity > existing_capacity:
            node_expansion_required = True
            logger.debug(f"Expanding volume {volume_id} from {existing_capacity} bytes to {capacity_bytes} bytes")
            vms_session.volumes.update(volume.id, size=capacity_bytes)
        else:
            node_expansion_required = False
            logger.debug(f"No expansion needed for volume {volume_id}, current size is sufficient")
        return types.CtrlExpandResp(
            capacity_bytes=capacity_bytes,
            node_expansion_required=node_expansion_required,
        )
    def CreateSnapshot(self, vms_session, source_volume_id, name, parameters=None):
        parameters = parameters or dict()
        cluster_name = parameters.get("cluster_name")
        volume_id = source_volume_id
        if not (volume := vms_session.volumes.one(name__endswith=volume_id)):
            raise Abort(NOT_FOUND, f"Unknown volume: {volume_id}")
        if not (view := vms_session.views.get_subsystem_by_id(_id=volume.view_id)):
            raise Abort(NOT_FOUND, f"Unknown subsystem: {volume.view_id}")

        # Full path is concatenation of view path and volume name.
        path = os.path.join(view.path, volume.name.lstrip("/"))
        tenant_id = view.tenant_id
        snapshot_name = parameters["csi.storage.k8s.io/volumesnapshot/name"]
        snapshot_namespace = parameters[
            "csi.storage.k8s.io/volumesnapshot/namespace"
        ]
        snapshot_name_fmt = parameters.get("snapshot_name_fmt", CONF.name_fmt)
        snapshot_name = snapshot_name_fmt.format(
            namespace=snapshot_namespace, name=snapshot_name, id=name
        )
        snapshot_name = snapshot_name.replace(":", "-").replace("/", "-")
        snap = vms_session.snapshots.ensure(name=snapshot_name, path=path, tenant_id=tenant_id)
        snp = types.Snapshot(
            size_bytes=0,  # indicates 'unspecified'
            snapshot_id=to_volume_id_with_metadata(snap.id, cluster_name),
            source_volume_id=to_volume_id_with_metadata(source_volume_id, cluster_name),
            creation_time=string_to_proto_timestamp(snap.created),
            ready_to_use=True,
        )
        return types.CreateSnapResp(snapshot=snp)

    def DeleteSnapshot(self, vms_session, snapshot_id):
        if vms_session.snapshots.get(snapshot_id):
            if vms_session.snapshots.has_not_finished_streams(snapshot_id):
                raise Exception(f"Unable to delete snapshot {snapshot_id!r} with active streams")
            vms_session.snapshots.delete_by_id(snapshot_id)
        return types.DeleteSnapResp()


################################################################
#
# Node
#
################################################################


class BlockNode(NodeBase, Instrumented):
    CAPABILITIES = [
        types.NodeCapabilityType.STAGE_UNSTAGE_VOLUME,
        types.NodeCapabilityType.EXPAND_VOLUME,
        types.NodeCapabilityType.GET_VOLUME_STATS,
    ]

    @cached_property
    def controller(self):
        return BlockController()

    def NodeStageVolume(
            self,
            volume_id,
            staging_target_path,
            volume_capability,
            exit_stack,
            luks_manager,
            vms_session=None,
            publish_context=None,
            volume_context=None,
            metrics_registry=None
    ):
        exit_stack.enter_context(volume_locked(volume_id))
        volume_context = volume_context or dict()
        volume_capabilities = _validate_capabilities(volume_capability, volume_context, publish_context)

        staging_target_path = local.path(staging_target_path)
        device_bind_path = get_device_bind_path(staging_target_path)

        logger.info("Checking if volume is already staged...")
        if MountInfo.get_mount_by_destination(
                dest_path=device_bind_path, resolve_symlink=CONF.resolve_mount_symlinks,
        ):
            logger.info(f"Volume {volume_id} already staged")
            return types.StageResp()  # idempotent

        if not publish_context:
            publish_context = self._get_publish_context_for_non_attach_required(
                vms_session=vms_session,
                node_id=CONF.node_id,
                volume_id=volume_id,
                volume_capability=volume_capability,
                volume_context=volume_context,
                exit_stack=exit_stack,
            )
        subsystem_nqn = publish_context["subsystem_nqn"]
        host_nqn = publish_context["host_nqn"]
        nguid = publish_context["nguid"]
        discovery_server = publish_context["discovery_server"]  # Either vip pool ip or fqdn
        need_resize = volume_context.get("need_resize", False)

        logger.info(f"Checking for existing NVMe session for subsystem {subsystem_nqn}...")
        if nvme_session := get_connected_session(host_nqn=host_nqn, subsystem_nqn=subsystem_nqn):
            # Nvme subsystem controllers already connected. No need to connect again.
            logger.info(f"{subsystem_nqn!r} already connected:")
            for line in stringify_dict(nvme_session.to_dict()):
                logger.info(line)
        else:
            logger.info(f"No existing session found, establishing new NVMe connection...")
            if not is_native_multipath_enabled():
                raise Abort(
                    FAILED_PRECONDITION,
                    "NVMe native multipath is not enabled on the system. "
                    "Please enable it to use NVMe subsystems."
                )
            host_id = string_to_static_uuid(host_nqn)
            logger.info(
                f"Connecting to NVMe targets for subsystem {subsystem_nqn} at {discovery_server} (host_id={host_id})"
            )
            if not (nvme_session := nvme_connect(
                discovery_server=discovery_server,
                host_nqn=host_nqn,
                host_id=host_id,
                subsystem_nqn=subsystem_nqn,
                metrics_registry=metrics_registry,
            )):
                raise Abort(
                    FAILED_PRECONDITION,
                    f"Failed to get NVMe session after connecting to {subsystem_nqn}"
                )
            logger.info(f"Successfully connected to NVMe subsystem {subsystem_nqn}")

        logger.info(f"Looking up NVMe device by NGUID {nguid}...")
        if not (device := get_nvme_device_by_nguid(nguid=nguid)):
            raise Abort(
                NOT_FOUND,
                f"NVMe device not found for subsystem {subsystem_nqn} and nguid {nguid}"
            )
        logger.info(f"Found NVMe device:")
        for line in stringify_dict(device.to_dict()):
            logger.info(line)

        device_path = device.DevicePath
        logger.info(f"Setting I/O policy to round-robin for device {device.Name}")
        change_io_policy(device_name=device.Name, io_policy="round-robin")

        # Disable NVMe controller timeout to prevent removal on temporary network issues
        disable_nvme_timeout(nvme_session)

        # Host encryption handling
        if luks_manager.requires_encryption():
            device_path = luks_manager.init_host_encryption(device_path=device_path)

        if volume_capabilities.is_filesystem:
            fs_type = volume_capabilities.fs_type
            logger.info(f"Formatting device {device_path} with {fs_type} filesystem (this may take several minutes for large volumes)...")
            with timing() as timer:
                formatted = format_device(requested_fs=fs_type, device=device_path)
            if formatted:
                logger.info(f"Device {device_path} formatted successfully in {timer.elapsed:.2f}s")
            # - check fs integrity only if:
            #   - device is not formatted. Can be if pvc is cloned from snapshot/volume or re-attached.
            #   - fs_type is not xfs. xfs does not require fsck.
            elif not fs_type == "xfs":
                check_fs_integrity(device=device_path)
                logger.info(f"Filesystem integrity check completed for {device_path}")
            # The source PVC may have a different size but was never attached and, therefore, never formatted.
            # In this case, the cloned PVC will be formatted as if it were a brand-new PVC,
            # eliminating the need for resizing.
            if need_resize and not formatted:
                logger.info(f"Resizing filesystem on device {device_path} (this may take several minutes)...")
                with temporary_mount(
                        src=device_path, tgt_dir=staging_target_path, fs_type=fs_type
                ) as temp_mount:
                    if luks_manager.requires_encryption():
                        luks_manager.luks_resize_device(device_path=device_path)
                    resize_device(device=device_path, target_mount=temp_mount, fs_type=fs_type)
                logger.info(f"Filesystem resize completed for {device_path}")

        logger.info(f"Binding device at {device_path} to {device_bind_path}.")
        staging_target_path.mkdir()
        device_bind_path.open("a").close()
        mount(
            src=device_path,
            tgt=device_bind_path,
            bind=True,
            metrics_registry=None,  # Don't count staging as mount operation
        )
        return types.StageResp()

    def NodeUnstageVolume(self, volume_id, staging_target_path, luks_manager, metrics_registry=None):
        staging_target_path = local.path(staging_target_path)
        device_bind_path = get_device_bind_path(staging_target_path)

        logger.info("Checking for existing mounts...")
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(
            src=device_bind_path, resolve_symlink=CONF.resolve_mount_symlinks,
        )

        if target_mounts:
            targets_mount_points = ", ".join(mount.mount_point for mount in target_mounts)
            logger.info(f"Staging path {device_bind_path} is being used by {targets_mount_points} targets.")
        if staging_mount:
            umount_safe(
                device_bind_path,
                metrics_registry=None,  # Don't count unstaging as unmount operation
            )
        else:
            logger.info(f"Device not found at {device_bind_path}")

        # If device is encrypted teardown accordingly
        luks_manager.luks_close_device()
        remove_path_if_not_mounted(device_bind_path)
        return types.UnstageResp()

    def NodePublishVolume(
            self,
            volume_id,
            target_path,
            exit_stack,
            luks_manager,
            staging_target_path=None,
            volume_capability=None,
            publish_context=None,
            readonly=False,
            vms_session=None,
            volume_context=None,
            metrics_registry=None
    ):
        volume_context = volume_context or dict()
        target_path = local.path(target_path)

        logger.info("Checking if volume is already published...")
        if MountInfo.get_mount_by_destination(
                dest_path=target_path, resolve_symlink=CONF.resolve_mount_symlinks,
        ):
            logger.info(f"Volume already published at {target_path}")
            return types.NodePublishResp()  # idempotent

        volume_capabilities = _validate_capabilities(volume_capability, volume_context, publish_context)
        is_ephemeral = volume_context.get("csi.storage.k8s.io/ephemeral") == "true"
        logger.info(f"Volume type: {'Ephemeral' if is_ephemeral else 'Persistent'}")
        if is_ephemeral:
            if not vms_session:
                raise Exception(
                    "Ephemeral Volume provisioning requires "
                    "configuring a global VMS credentials secret or nodePublishSecretRef secret reference."
                )
            # EV volumes doesn't have staging path. Use target path as staging path.
            # Later staging path will be converted to <target_path>/device
            staging_target_path = target_path
            target_path.mkdir()
            logger.info("Retrieving publish context for ephemeral volume...")
            publish_context = self._get_publish_context_for_ev_volumes(
                volume_context=volume_context,
                volume_id=volume_id,
                vms_session=vms_session,
                volume_capability=volume_capability,
                exit_stack=exit_stack,
            )
            self.NodeStageVolume.__wrapped__(
                self,
                volume_id=volume_id,
                staging_target_path=staging_target_path,
                volume_capability=volume_capability,
                exit_stack=exit_stack,
                luks_manager=luks_manager,
                vms_session=vms_session,
                publish_context=publish_context,
                volume_context=volume_context,
                metrics_registry=metrics_registry,
            )
        assert staging_target_path
        device_bind_path = get_device_bind_path(staging_target_path)
        logger.info(f"Device bind path: {device_bind_path}")
        mount_flags = volume_capabilities.mount_flags
        if readonly:
            mount_flags.append("ro")

        is_file_system = volume_capabilities.is_filesystem
        fs_type = volume_capabilities.fs_type
        if is_file_system:
            logger.info(f"Verifying filesystem type {fs_type} on device...")
            if fs_type != get_filesystem_type(device_bind_path):
                raise Exception(
                    f"Device at {device_bind_path} is not formatted with {volume_capabilities.fs_type}."
                )
            if fs_type == "xfs":
                # By default, xfs does not allow mounting of two volumes with the same filesystem uuid.
                # Force ignore this uuid to be able to mount volume + its clone/restored snapshot on the same node.
                mount_flags.append("nouuid")
                logger.info("Added 'nouuid' flag for XFS filesystem")
            logger.info(
                f"Filesystem mode detected. "
                f"Creating directory at {target_path} for mounting device."
            )
            # Filesystem volumes are mounted as directories because the operating system
            # treats them as a hierarchical storage structure.
            target_path.mkdir()
            meta_file = target_path[".vast-csi-meta"]
            self._store_meta_file(
                meta_file=meta_file,
                volume_id=volume_id,
                is_ephemeral=is_ephemeral,
                vms_session=vms_session,
                luks_manager=luks_manager,
            )
            try:
                mount(
                    src=device_bind_path,
                    tgt=target_path,
                    flags=mount_flags,
                    fs_type=fs_type,
                    metrics_registry=metrics_registry,
                )
            except Exception:
                meta_file.delete()
        else:
            logger.info(
                f"Block device mode detected. "
                f"Creating a placeholder file at {target_path} for binding device."
            )
            # Block devices are raw storage devices that are accessed as single files by the operating system.
            target_path.open("a").close()
            mount(
                src=device_bind_path,
                tgt=target_path,
                flags=mount_flags,
                bind=True,
                metrics_registry=metrics_registry,
            )

        logger.info("Verifying mount...")
        if not MountInfo.get_mount_by_destination(
                dest_path=target_path, resolve_symlink=CONF.resolve_mount_symlinks,
        ):
            err_msg = (
                f"An unexpected error occurred while attempting to mount"
                f" {device_bind_path} to {target_path}."
            )
            if is_file_system:
                err_msg += f" Check if mount options {mount_flags} are correct for chosen filesystem {fs_type}."
            raise Abort(NOT_FOUND, err_msg)
        return types.NodePublishResp()

    def NodeUnpublishVolume(self, volume_id, target_path, luks_manager, vms_session=None, metrics_registry=None):
        target_path = local.path(target_path)
        meta_file = target_path[".vast-csi-meta"]
        if MountInfo.get_mount_by_destination(
                dest_path=target_path, resolve_symlink=CONF.resolve_mount_symlinks,
        ):
            umount_safe(
                target_path,
                metrics_registry=metrics_registry,
            )
        else:
            logger.info(f"Device not found at {target_path}")
        if meta_file.exists():
            meta = self._read_and_process_meta_file(
                meta_file=meta_file,
                volume_id=volume_id,
                vms_session=vms_session,
            )
            if meta.get("is_ephemeral"):
                # EV volumes doesn't have staging path. Use target path as staging path.
                self.NodeUnstageVolume.__wrapped__(
                    self,
                    volume_id=volume_id,
                    luks_manager=luks_manager,
                    staging_target_path=target_path,
                    metrics_registry=metrics_registry,
                )
            logger.info("Removing metadata file...")
            os.remove(meta_file)

        remove_path_if_not_mounted(target_path)
        return types.NodeUnpublishResp()

    def NodeExpandVolume(
            self,
            volume_id,
            volume_path,
            capacity_range,
            staging_target_path,
            volume_capability,
            exit_stack,
            luks_manager,
    ):
        exit_stack.enter_context(volume_locked(volume_id))
        volume_capabilities = _validate_capabilities(volume_capability)
        device_bind_path = get_device_bind_path(staging_target_path)
        requested_capacity = capacity_range.required_bytes

        logger.info(f"Requested capacity for volume {volume_id}: {requested_capacity} bytes")
        staging_mount = MountInfo.get_mount_by_destination(
            dest_path=device_bind_path, resolve_symlink=CONF.resolve_mount_symlinks,
        )
        if not staging_mount:
            raise Abort(NOT_FOUND, f"Mount information not found for staging path: {device_bind_path}")

        # Host encryption resize handling
        if luks_manager.luks_device_exists():
            # Note: StorageClass secret is present in this endpoint since kubernetes 1.25.
            # https://kubernetes.io/blog/2022/09/21/kubernetes-1-25-use-secrets-while-expanding-csi-volumes-on-node-alpha/
            # Without secret you still can use host encryption, but you will not be able to resize the volume.
            # Or use "global" secret as a workaround.
            if not luks_manager.passphrase:
                raise Abort(
                    FAILED_PRECONDITION,
                    "LUKS passphrase is required to resize encrypted volumes. "
                    "Ensure your Kubernetes cluster supports NodeExpandSecret, or use a global secret that includes the passphrase."
                )

            device_path = luks_manager.luks_device_path
            origin_device_path = luks_manager.get_backing_block_device()
            logger.info(f"Original device path for LUKS volume: {origin_device_path}")
            luks_manager.luks_resize_device(device_path=origin_device_path)
        else:
            device_path = origin_device_path = staging_mount.block_device

        if volume_capabilities.is_filesystem:
            fs_type = get_filesystem_type(device_bind_path)
            if not MountInfo.get_mount_by_destination(
                    dest_path=volume_path, resolve_symlink=CONF.resolve_mount_symlinks,
            ):
                logger.info(f"Volume path {volume_path} is not mounted. Create tmp mount.")
                # It is possible that NodeExpandVolume can be triggered before NodePublishVolume
                # in scenario when:
                #    1. Volume is created
                #    2. Volume is expanded
                #    3. Volume is published
                # for such scenario we need to create temporary mount to resize the filesystem.
                with temporary_mount(
                        src=device_path, tgt_dir=staging_target_path, fs_type=fs_type
                ) as temp_mount:
                    resize_device(device=device_path, target_mount=temp_mount, fs_type=fs_type)
            else:
                resize_device(
                    device=device_path,
                    target_mount=volume_path,
                    fs_type=fs_type,
                )
        else:
            existing_capacity = get_device_size(origin_device_path)
            if existing_capacity < requested_capacity:
                raise Exception(
                    f"Requested capacity {requested_capacity} exceeds the current capacity {existing_capacity}. "
                    f"This may indicate the updated size has not yet been propagated."
                )
        return types.NodeExpandResp(capacity_bytes=requested_capacity)

    def NodeGetVolumeStats(self, volume_id, volume_path, luks_manager):
        if luks_manager.luks_device_exists():
            # If the volume is encrypted, we need to get stats from the backing block device
            return self._get_block_stats(luks_manager.get_backing_block_device())

        target_mount = MountInfo.get_mount_by_destination(
            dest_path=volume_path, resolve_symlink=CONF.resolve_mount_symlinks,
        )
        if not target_mount:
            raise Abort(NOT_FOUND, f"Mount information not found for volume path: {volume_path}")
        if target_mount.has_blockdev_root:
            # Get the device path associated with the mount
            return self._get_block_stats(target_mount.block_device)
        else:
            return self._get_fs_stats(volume_path)


def serve(server: grpc.Server, conf: Config):
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf
    identity = BlockIdentity()
    csi_grpc.add_IdentityServicer_to_server(identity, server)
    identity.capabilities.append(types.ExpansionType.ONLINE)

    if conf.mode in {CONTROLLER, CONTROLLER_AND_NODE}:
        identity.controller = BlockController()
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_grpc.add_ControllerServicer_to_server(identity.controller, server)
        conf.fake_quota_store.mkdir()
        conf.fake_snapshot_store.mkdir()

    if conf.mode in {NODE, CONTROLLER_AND_NODE}:
        try_nvme_probes()
        identity.node = BlockNode()
        csi_grpc.add_NodeServicer_to_server(identity.node, server)
