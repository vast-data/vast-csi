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

import os
from datetime import datetime
from tempfile import mkdtemp
from json import JSONDecodeError
from plumbum import local
import grpc

from easypy.tokens import CONTROLLER_AND_NODE, CONTROLLER, NODE
from easypy.caching import cached_property
from easypy.humanize import yesno_to_bool

from vast_csi.logging import logger
from vast_csi.utils import (
    get_mount,
    normalize_mount_options,
    normalize_volume_id,
    string_to_proto_timestamp,
    get_random_fqdn_prefix,
    wrap_ipv6,
    string_to_static_uuid,
    path_exists,
)
from vast_csi.filesystem_utils import resource_locked, mount as _mount, umount as _umount
from vast_csi.proto import csi_pb2_grpc as csi_grpc
from vast_csi import csi_types as types
from vast_csi.csi_types import (
    FAILED_PRECONDITION,
    INVALID_ARGUMENT,
    ALREADY_EXISTS,
    NOT_FOUND,
    ABORTED,
    UNKNOWN,
    OUT_OF_RANGE,
)
from vast_csi.builders import (
    EmptyVolumeBuilder,
    VolumeFromSnapshotBuilder,
    VolumeFromVolumeBuilder,
    TestVolumeBuilder,
    StaticVolumeBuilder,
    to_volume_id_with_metadata,
)
from vast_csi.exceptions import (
    Abort,
    ApiError,
    VolumeAlreadyExists,
    SourceNotFound,
    OperationNotSupported,
    UmountTimedOut,
)
from vast_csi.configuration import Config
import vast_csi.capabilities as cap_lib
from vast_csi.plugins.base import (
    IdentityBase,
    ControllerBase,
    NodeBase,
    Instrumented,
)
from vast_csi.mtls_utils import MtlsManager


CONF = None
ServiceCapabilities = cap_lib.ServiceCapabilities(
    support_filesystem=True, support_block=False, can_many_rwx=True
)

################################################################
#
# Helpers
#
################################################################


def mount(src, tgt, flags="", metrics_registry=None):
    flags_list = [f.strip() for f in flags.split(",") if f.strip()]
    if CONF.mock_vast:
        flags_list += "port=2049,nolock,vers=3".split(",")
    return _mount(
        src,
        tgt,
        flags=flags_list,
        metrics_registry=metrics_registry,
        metrics_operation="nfs",
        timeout=CONF.mount_umount_timeout,
    )


def umount(path, ignore_not_mounted=False, lazy=False, metrics_registry=None):
    return _umount(
        path,
        ignore_not_mounted=ignore_not_mounted,
        lazy=lazy,
        metrics_registry=metrics_registry,
        metrics_operation="nfs",
        timeout=CONF.mount_umount_timeout,
    )



def _validate_capabilities(capabilities):
    try:
        return ServiceCapabilities.make_and_validate(capabilities)
    except cap_lib.CapValidationError as exc:
        raise Abort(INVALID_ARGUMENT, exc.render(color=False))


################################################################
#
# Identity
#
################################################################


class CsiIdentity(IdentityBase, Instrumented):
  pass


################################################################
#
# Controller
#
################################################################

class CsiController(ControllerBase, Instrumented):

    CAPABILITIES = [
        types.CtrlCapabilityType.CREATE_DELETE_VOLUME,
        types.CtrlCapabilityType.PUBLISH_UNPUBLISH_VOLUME,
        # types.CtrlCapabilityType.LIST_VOLUMES,
        types.CtrlCapabilityType.EXPAND_VOLUME,
        types.CtrlCapabilityType.CREATE_DELETE_SNAPSHOT,
        # types.CtrlCapabilityType.LIST_SNAPSHOTS,
        types.CtrlCapabilityType.CLONE_VOLUME,
        # types.CtrlCapabilityType.GET_CAPACITY,
        # types.CtrlCapabilityType.PUBLISH_READONLY,
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
        if not vms_session.quotas.one(name=volume_id):
            raise Abort(NOT_FOUND, f"Volume {volume_id} does not exist")
        try:
            _validate_capabilities(volume_capabilities)
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
        ephemeral_volume_name=None,
    ):
        volume_capabilities = _validate_capabilities(volume_capabilities)
        parameters = parameters or dict()

        # Take appropriate builder for volume, snapshot or test builder
        if CONF.mock_vast:
            builder_cls = TestVolumeBuilder
        else:
            if not volume_content_source:
                builder_cls = EmptyVolumeBuilder

            elif volume_content_source.snapshot.snapshot_id:
                builder_cls = VolumeFromSnapshotBuilder

            elif volume_content_source.volume.volume_id:
                builder_cls = VolumeFromVolumeBuilder

            else:
                raise ValueError(
                    "Invalid condition. Either volume_content_source"
                    " or test environment variable should be provided"
                )
        builder = builder_cls.from_parameters(
            conf=CONF,
            vms_session=vms_session,
            name=name,
            volume_capabilities=volume_capabilities,
            capacity_range=capacity_range,
            parameters=parameters,
            volume_content_source=volume_content_source,
            ephemeral_volume_name=ephemeral_volume_name,
        )
        # Create volume, volume from snapshot or mount local path (for testing purposes)
        try:
            volume = builder.build_volume()
        except SourceNotFound as exc:
            raise Abort(NOT_FOUND, exc.message)
        except VolumeAlreadyExists as exc:
            raise Abort(ALREADY_EXISTS, exc.message)
        return types.CreateResp(volume=volume)

    def _delete_data_from_storage(self, vms_session, path, tenant_id):
        if CONF.avoid_trash_api.expired:
            try:
                logger.info(f"Attempting trash API to delete {path}")
                vms_session.folders.delete(path, tenant_id)
                return  # Successfully deleted. Prevent using local mounting
            except OperationNotSupported as exc:
                logger.info(f"Trash API not available {exc}")
                CONF.avoid_trash_api.reset()

        logger.info(f"Use local mounting to delete {path}")
        path = local.path(path)
        volume_id = path.name
        assert CONF.deletion_view_policy, (
            "Ensure that deletionViewPolicy is properly "
            "configured in your Helm configuration to perform local volume deletion."
        )
        view_policy = vms_session.viewpolicies.one(name=CONF.deletion_view_policy, fail_if_missing=True)
        assert tenant_id == view_policy.tenant_id, (
            f"Volume and deletionViewPolicy must be in the same tenant. "
            f"Make sure deletionViewPolicy belongs to tenant {tenant_id} or use Trash API for deletion."
        )
        if CONF.use_local_ip_for_mount:
            nfs_server_ip = CONF.use_local_ip_for_mount
        else:
            assert CONF.deletion_vip_pool, (
                "Ensure that deletionVipPool is properly "
                "configured in your Helm configuration to perform local volume deletion."
            )
            nfs_server_ip = vms_session.vippools.get_vip(CONF.deletion_vip_pool, view_policy.tenant_id)

        logger.info(f"Creating temporary base view.")
        with vms_session.views.temp_view(path.dirname, view_policy.id, view_policy.tenant_id) as base_view:
            nfs_server_ip = wrap_ipv6(nfs_server_ip)
            mount_spec = f"{nfs_server_ip}:{base_view.alias}"
            mounted = False
            tmpdir = local.path(mkdtemp())  # convert string to local.path
            tmpdir['.csi-unmounted'].touch()

            try:
                mount(mount_spec, tmpdir, flags=",".join(CONF.mount_options))
                assert not tmpdir['.csi-unmounted'].exists()
                mounted = True

                if tmpdir[volume_id].exists():
                    logger.info(f"deleting {tmpdir[volume_id]}")
                    tmpdir[volume_id].delete()
                    logger.info(f"done deleting {tmpdir[volume_id]}")
                else:
                    logger.info(f"already deleted {tmpdir[volume_id]}")
            except FileNotFoundError as exc:
                if 'No such file or directory' in str(exc):
                    logger.warning(
                        'It appears that multiple processes are attempting to clean a single directory,'
                        ' leading to unforeseeable concurrent access to the identical file or directory.'
                        ' The cleaning process will be repeated.'
                    )
                    raise Abort(
                        ABORTED,
                        f"Concurrent access to an identical file/directory has been detected."
                        f" A new attempt will be made.",
                    )
                else:
                    raise
            except OSError as exc:
                if 'not empty' in str(exc):
                    for i, item in enumerate(tmpdir[volume_id].list()):
                        if i > 9:
                            logger.debug(" ...")
                            break
                        logger.warning(f" - {item}")
                raise
            finally:
                if mounted:
                    umount(tmpdir, ignore_not_mounted=True)
                os.remove(tmpdir['.csi-unmounted'])  # will fail if still mounted somehow
                os.rmdir(tmpdir)  # will fail if not empty directory

    def DeleteVolume(self, vms_session, volume_id):
        volume_id = normalize_volume_id(volume_id)
        vms_session.globalsnapstreams.ensure_snapshot_stream_deleted(name=f"strm-{volume_id}")
        if quota := vms_session.quotas.one(name=volume_id):
            # this is a check we have to do until Vast provides access to orphaned snapshots (ORION-135599)
            might_use_trash_folder = not CONF.dont_use_trash_api
            if might_use_trash_folder and (snaps := vms_session.snapshots.has_snapshots(quota.path)):
                snap_ids = ", ".join(str(s.id) for s in snaps)
                raise Exception(f"Unable to delete {volume_id} as it holds snapshots: [{snap_ids}]")
            try:
                self._delete_data_from_storage(vms_session, quota.path, quota.tenant_id)
            except OSError as exc:
                if 'not empty' not in str(exc):
                    raise
                if snaps := vms_session.snapshots.has_snapshots(quota.path):
                    # this is expected when the volume has snapshots
                    logger.info(f"{quota.path} will remain due to remaining {len(snaps)} snapshots")
                else:
                    raise
            logger.info(f"Data removed: {quota.path}")

            vms_session.views.delete(path=quota.path)
            logger.info(f"View removed: {quota.path}")

            vms_session.quotas.delete_by_id(quota.id)
            logger.info(f"Quota removed: {quota.id}")

        logger.info(f"Removed volume: {volume_id}")
        return types.DeleteResp()

    def ControllerPublishVolume(
            self, vms_session, node_id, volume_id, volume_capability, volume_context=None, exit_stack=None
    ):
        volume_context = dict(volume_context or dict())
        volume_capabilities = _validate_capabilities(volume_capability)

        if volume_id.startswith("/"):
            # Assumed consuming existing volume where user specified full path to view in volumeHandle attribute.
            if volume_id != "/":
                # keep path consistent.
                volume_id = volume_id.rstrip("/")
            logger.info(f"Binding static volume: {volume_id}")
            export_path = volume_context["root_export"] = volume_id
            name = string_to_static_uuid(volume_id)
            create_view = yesno_to_bool(volume_context.get("static_pv_create_views", "no"))
            create_quota = yesno_to_bool(volume_context.get("static_pv_create_quotas", "no"))
            builder = StaticVolumeBuilder.from_parameters(
                conf=CONF,
                vms_session=vms_session,
                name=name,
                volume_capabilities=volume_capabilities,
                parameters=volume_context,
                create_view=create_view,
                create_quota=create_quota,
            )
            try:
                volume_context = builder.build_volume()
            except SourceNotFound as exc:
                raise Abort(NOT_FOUND, exc.message)
            except VolumeAlreadyExists as exc:
                raise Abort(ALREADY_EXISTS, exc.message)

        else:
            root_export = CONF.sanity_test_nfs_export if CONF.mock_vast else local.path(volume_context["root_export"])
            # Build export path for snapshot or volume
            if snapshot_base_path := volume_context.get("snapshot_base_path"):
                # Snapshot
                export_path = str(root_export[snapshot_base_path])
            else:
                # Volume
                export_path = str(root_export[volume_id])

        if CONF.csi_sanity_test and CONF.node_id != node_id:
            # for a test that tries to fake a non-existent node
            raise Abort(NOT_FOUND, f"Unknown volume: {node_id}")

        vip_pool_name = volume_context.get("vip_pool_name")
        vip_pool_fqdn = volume_context.get("vip_pool_fqdn")
        if vip_pool_fqdn:
            nfs_server_ip = vip_pool_fqdn
            if volume_context.get("vip_pool_fqdn_random_prefix"):
                prefix = get_random_fqdn_prefix()
                nfs_server_ip = f"{prefix}.{nfs_server_ip}"
        elif vip_pool_name or CONF.mock_vast:
            nfs_server_ip = vms_session.vippools.get_vip(vip_pool_name=vip_pool_name)
        else:
            nfs_server_ip = CONF.use_local_ip_for_mount
            assert nfs_server_ip, f"{nfs_server_ip=}"
            logger.info(f"Using local IP for mount: {nfs_server_ip}")

        return types.CtrlPublishResp(
            publish_context=dict(
                export_path=export_path,
                nfs_server_ip=wrap_ipv6(nfs_server_ip),
                # volume_context is not accessible for static volumes. Pass mount_options through publish_context.
                mount_options=volume_capabilities.mount_flags_str,
            )
        )

    def ControllerUnpublishVolume(self, node_id, volume_id):
        return types.CtrlUnpublishResp()

    def ControllerExpandVolume(self, vms_session, volume_id, capacity_range):
        volume_id = normalize_volume_id(volume_id)
        requested_capacity = capacity_range.required_bytes

        if not (quota := vms_session.quotas.one(name=volume_id)):
            raise Abort(NOT_FOUND, f"Not found quota with id: {volume_id}")

        existing_capacity = quota.hard_limit
        if requested_capacity <= existing_capacity:
            capacity_bytes = existing_capacity
        else:
            try:
                vms_session.quotas.update(quota.id, hard_limit=requested_capacity)
            except ApiError as exc:
                raise Abort(OUT_OF_RANGE, f"Failed updating quota {quota.id}: {exc}")
            capacity_bytes = requested_capacity

        return types.CtrlExpandResp(
            capacity_bytes=capacity_bytes,
            node_expansion_required=False,
        )

    def CreateSnapshot(self, vms_session, source_volume_id, name, parameters=None):

        parameters = parameters or dict()
        cluster_name = parameters.get("cluster_name")
        volume_id = source_volume_id
        if not (quota := vms_session.quotas.one(name=volume_id)):
            raise Abort(NOT_FOUND, f"Unknown volume: {volume_id}")

        if CONF.mock_vast:

            try:
                with CONF.fake_snapshot_store[name].open("rb") as f:
                    snp = types.Snapshot()
                    snp.ParseFromString(f.read())
                if snp.source_volume_id != volume_id:
                    raise Abort(
                        ALREADY_EXISTS, f"Snapshot name '{name}' is already taken"
                    )
            except FileNotFoundError:
                ts = types.Timestamp()
                ts.FromDatetime(datetime.utcnow())
                snp = types.Snapshot(
                    size_bytes=0,  # indicates 'unspecified'
                    snapshot_id=name,
                    source_volume_id=volume_id,
                    creation_time=ts,
                    ready_to_use=True,
                )
                with CONF.fake_snapshot_store[name].open("wb") as f:
                    f.write(snp.SerializeToString())
        else:
            # Create snapshot using the same path as quota has.
            path = quota.path
            tenant_id = quota.tenant_id
            snapshot_name = parameters["csi.storage.k8s.io/volumesnapshot/name"]
            snapshot_namespace = parameters[
                "csi.storage.k8s.io/volumesnapshot/namespace"
            ]
            snapshot_name_fmt = parameters.get("snapshot_name_fmt", CONF.name_fmt)
            snapshot_name = snapshot_name_fmt.format(
                namespace=snapshot_namespace, name=snapshot_name, id=name
            )
            snapshot_name = snapshot_name.replace(":", "-").replace("/", "-")
            try:
                snap = vms_session.snapshots.ensure(name=snapshot_name, path=path, tenant_id=tenant_id)
            except ApiError as exc:
                handled = False
                if exc.response.status_code == 400:
                    try:
                        [(k, [v])] = exc.response.json().items()
                    except (ValueError, JSONDecodeError):
                        pass
                    else:
                        if (k, v) == ("name", "This field must be unique."):
                            snap = vms_session.snapshots.one(name=snapshot_name)
                            if snap.path.strip("/") != path.strip("/"):
                                raise Abort(
                                    ALREADY_EXISTS,
                                    f"Snapshot name '{name}' is already taken",
                                ) from None
                            else:
                                handled = True
                if not handled:
                    raise Abort(INVALID_ARGUMENT, str(exc))

            snp = types.Snapshot(
                size_bytes=0,  # indicates 'unspecified'
                snapshot_id=to_volume_id_with_metadata(snap.id, cluster_name),
                source_volume_id=to_volume_id_with_metadata(source_volume_id, cluster_name),
                creation_time=string_to_proto_timestamp(snap.created),
                ready_to_use=True,
            )

        return types.CreateSnapResp(snapshot=snp)

    def DeleteSnapshot(self, vms_session, snapshot_id):
        if CONF.mock_vast:
            CONF.fake_snapshot_store[snapshot_id].delete()
        else:
            snapshot = vms_session.snapshots.get(snapshot_id, fail_if_missing=False)
            if not snapshot:
                return types.DeleteSnapResp()
            if vms_session.snapshots.has_not_finished_streams(snapshot.id):
                raise Exception(f"Unable to delete snapshot {snapshot.id!r} with active streams")

            vms_session.snapshots.delete_by_id(snapshot_id)
            if vms_session.quotas.one(path=snapshot.path, tenant_id=snapshot.tenant_id):
                pass  # quotas still exist
            elif vms_session.snapshots.has_snapshots(snapshot.path):
                pass  # other snapshots still exist
            else:
                logger.info(f"last snapshot for {snapshot.path}, and no more quotas - let's delete this directory")
                self._delete_data_from_storage(vms_session, snapshot.path, snapshot.tenant_id)

        return types.DeleteSnapResp()

    @classmethod
    def _to_volume_id(cls, path):
        vol_id = str(local.path(path).relative_to(CONF.sanity_test_nfs_export))
        return None if vol_id.startswith("..") else vol_id


################################################################
#
# Node
#
################################################################


class CsiNode(NodeBase, Instrumented):

    CAPABILITIES = [
        types.NodeCapabilityType.EXPAND_VOLUME,
        types.NodeCapabilityType.GET_VOLUME_STATS,
    ]

    @cached_property
    def controller(self):
        return CsiController()

    def NodePublishVolume(
        self,
        volume_id,
        target_path,
        exit_stack,
        mtls_manager,
        vms_session=None,
        volume_capability=None,
        publish_context=None,
        readonly=False,
        volume_context=None,
        metrics_registry=None
    ):
        exit_stack.enter_context(resource_locked(volume_id, abort_on_error=True))
        volume_context = volume_context or dict()
        if (
            is_ephemeral := volume_context
            and volume_context.get("csi.storage.k8s.io/ephemeral") == "true"
        ):
            if not vms_session:
                raise Abort(
                    FAILED_PRECONDITION,
                    "Ephemeral Volume provisioning requires "
                    "configuring a global VMS credentials secret or nodePublishSecretRef secret reference."
                )
            eph_volume_name_fmt = volume_context.get("eph_volume_name_fmt", CONF.name_fmt)
            pod_uid = volume_context["csi.storage.k8s.io/pod.uid"]
            pod_name = volume_context["csi.storage.k8s.io/pod.name"]
            pod_namespace = volume_context["csi.storage.k8s.io/pod.namespace"]
            eph_volume_name = eph_volume_name_fmt.format(
                namespace=pod_namespace, name=pod_name, id=pod_uid
            )
            publish_context = self._get_publish_context_for_ev_volumes(
                volume_context=volume_context,
                volume_id=volume_id,
                vms_session=vms_session,
                volume_capability=volume_capability,
                ephemeral_volume_name=eph_volume_name,
                exit_stack=exit_stack,
            )
        elif not volume_capability:
            raise Abort(INVALID_ARGUMENT, "missing 'volume_capability'")

        if not publish_context:
            publish_context = self._get_publish_context_for_non_attach_required(
                vms_session=vms_session,
                node_id=CONF.node_id,
                volume_id=volume_id,
                volume_capability=volume_capability,
                volume_context=volume_context,
                exit_stack=exit_stack,
            )

        nfs_server_ip = publish_context["nfs_server_ip"]

        schema = "1" if not volume_context else volume_context.get("schema", "1")
        if schema == "2":
            export_path = volume_context["export_path"]
        else:
            export_path = publish_context["export_path"]
        mount_spec = f"{nfs_server_ip}:{export_path}"

        _validate_capabilities(volume_capability)
        target_path = local.path(target_path)

        if not target_path.is_dir():
            pass
        elif found_mount := get_mount(target_path):
            opts = set(found_mount.opts.split(","))
            is_readonly = "ro" in opts
            if found_mount.device != mount_spec:
                _, _, mounted_path = found_mount.device.partition(":")
                _, _, expected_path = mount_spec.partition(":")
                if mounted_path == expected_path:
                    logger.warning(
                        f"{volume_id} found existing mount {found_mount.device} "
                        f"instead of {mount_spec} — lazy-unmounting stale entry"
                    )
                    umount(target_path, lazy=True)
                    # fall through to fresh mount below (target_path directory still exists)
                else:
                    raise Abort(
                        ALREADY_EXISTS,
                        f"Volume already mounted from {found_mount.device} instead of {mount_spec}",
                    )
            elif is_readonly != readonly:
                raise Abort(
                    ALREADY_EXISTS,
                    f"Volume already mounted as {'readonly' if is_readonly else 'readwrite'}",
                )
            else:
                logger.info(f"{volume_id} is already mounted: {found_mount}")
                return types.NodePublishResp()

        target_path.mkdir()
        meta_file = target_path[".vast-csi-meta"]
        self._store_meta_file(
            meta_file=meta_file,
            volume_id=volume_id,
            is_ephemeral=is_ephemeral,
            vms_session=vms_session,
            extra_data={"has_mtls": True} if mtls_manager.requires_mtls() else None,
        )
        logger.info(f"created: {target_path}")

        flags = ["ro"] if readonly else []
        if volume_capability.mount.mount_flags:
            flags += volume_capability.mount.mount_flags
        else:
            flags += normalize_mount_options(
                volume_context.get("mount_options", publish_context.get("mount_options", ""))
            )
        
        # Add mTLS mount flags if enabled
        try:
            flags += mtls_manager.to_mount_flags(volume_id=volume_id)
        except Exception as e:
            meta_file.delete()
            raise Abort(
                FAILED_PRECONDITION,
                f"Failed to load mTLS credentials: {e}"
            )
        
        if CONF.nfs_services_wait:
            from vast_csi.nfs_services import wait_registered
            if not wait_registered(CONF.nfs_services_wait):
                logger.warning(
                    f"{volume_id}: NFS services {CONF.nfs_services_wait} not registered "
                    "before mount; proceeding (kubelet will retry on failure)"
                )

        try:
            mount(
                mount_spec,
                target_path,
                flags=",".join(flags),
                metrics_registry=metrics_registry,
            )
            logger.info(f"mounted: {target_path} flags: {flags}")
        except Exception:
            meta_file.delete()
            # Clean up mTLS credentials on mount failure
            if mtls_manager.requires_mtls():
                mtls_manager.delete_credentials(volume_id)

            raise

        return types.NodePublishResp()

    def NodeUnpublishVolume(
            self,
            volume_id,
            target_path,
            exit_stack,
            vms_session=None,
            metrics_registry=None,
    ):
        exit_stack.enter_context(resource_locked(volume_id, abort_on_error=True))
        target_path = local.path(target_path)
        meta_file = target_path[".vast-csi-meta"]

        if not path_exists(target_path, timeout=CONF.mount_umount_timeout):
            logger.info(f"{target_path} does not exist - no need to remove")
        else:
            # make sure we're really unmounted before we delete anything
            for i in range(CONF.unmount_attempts):
                mount_info = get_mount(target_path, timeout=CONF.mount_umount_timeout)
                if not mount_info:
                    logger.info(f"{target_path} is not mounted")
                    break
                try:
                    umount(
                        target_path,
                        ignore_not_mounted=False,
                        metrics_registry=metrics_registry,
                    )
                except UmountTimedOut as exc:
                    if not CONF.force_lazy_umount_on_timeout:
                        raise Abort(UNKNOWN, str(exc))
                    logger.warning(f"umount timed out for {target_path}, retrying with lazy unmount (-l).")
                    umount(target_path, lazy=True, ignore_not_mounted=False, metrics_registry=metrics_registry)
            else:
                raise Abort(
                    UNKNOWN,
                    f"Stuck in unmount loop of {target_path} too many times ({CONF.unmount_attempts})",
                )
            has_mtls = False
            if meta_file.exists():
                meta = self._read_and_process_meta_file(
                    meta_file=meta_file,
                    volume_id=volume_id,
                    vms_session=vms_session,
                )
                has_mtls = meta.get("has_mtls", False)
                os.remove(meta_file)
            if has_mtls:
                MtlsManager.delete_credentials(volume_id)
            logger.info(f"Deleting {target_path}")
            os.rmdir(target_path)  # don't use plumbum's .delete to avoid the dangerous rmtree
            logger.info(f"{target_path} removed successfully")
        return types.NodeUnpublishResp()

    def NodeExpandVolume(
            self,
            volume_id,
            volume_path,
            capacity_range=None,
            staging_target_path=None,
            volume_capability=None,
    ):
        """No-op for NFS volumes."""
        if not os.path.ismount(volume_path):
            raise Abort(NOT_FOUND, f"{volume_path} is not a mountpoint")
        
        requested_capacity = capacity_range.required_bytes if capacity_range else 0
        return types.NodeExpandResp(capacity_bytes=requested_capacity)

    def NodeGetVolumeStats(self, volume_id, volume_path):
        if not os.path.ismount(volume_path):
            raise Abort(NOT_FOUND, f"{volume_path} is not a mountpoint")
        # See http://man7.org/linux/man-pages/man2/statfs.2.html for details.
        return self._get_fs_stats(volume_path)


def serve(server: grpc.Server, conf: Config):
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf
    identity = CsiIdentity()
    csi_grpc.add_IdentityServicer_to_server(identity, server)
    identity.capabilities.append(types.ExpansionType.ONLINE)

    if conf.mode in {CONTROLLER, CONTROLLER_AND_NODE}:
        identity.controller = CsiController()
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_grpc.add_ControllerServicer_to_server(identity.controller, server)
        conf.fake_quota_store.mkdir()
        conf.fake_snapshot_store.mkdir()

    if conf.mode in {NODE, CONTROLLER_AND_NODE}:
        identity.node = CsiNode()
        csi_grpc.add_NodeServicer_to_server(identity.node, server)
