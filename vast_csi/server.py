# Copyright 2015 gRPC authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""The Python implementation of the GRPC helloworld.Greeter server."""

import os
import re
from random import randint
from concurrent import futures
from functools import wraps
from pprint import pformat
from datetime import datetime
import inspect
from tempfile import mkdtemp

import json
from json import JSONDecodeError
from plumbum import cmd
from plumbum import local, ProcessExecutionError
import grpc
from requests.exceptions import HTTPError

from easypy.tokens import CONTROLLER_AND_NODE, CONTROLLER, NODE, COSI_PLUGIN
from easypy.misc import kwargs_resilient
from easypy.caching import cached_property
from easypy.bunch import Bunch
from easypy.exceptions import TException
from easypy.collections import separate

from .logging import logger, init_logging
from .utils import (
    patch_traceback_format,
    get_mount,
    normalize_mount_options,
    string_to_proto_timestamp,
    is_valid_ip,
)
from .proto import csi_pb2_grpc as csi_grpc
from .proto import cosi_pb2_grpc as cosi_grpc
from . import csi_types as types
from .volume_builder import EmptyVolumeBuilder, VolumeFromSnapshotBuilder, VolumeFromVolumeBuilder, TestVolumeBuilder
from .exceptions import (
    Abort,
    ApiError,
    MissingParameter,
    MountFailed,
    VolumeAlreadyExists,
    SourceNotFound,
    OperationNotSupported,
    LookupFieldError,
)
from .vms_session import get_vms_session, VmsSession
from .configuration import Config


CONF = None

################################################################
#
# Helpers
#
################################################################


FAILED_PRECONDITION = grpc.StatusCode.FAILED_PRECONDITION
INVALID_ARGUMENT = grpc.StatusCode.INVALID_ARGUMENT
ALREADY_EXISTS = grpc.StatusCode.ALREADY_EXISTS
NOT_FOUND = grpc.StatusCode.NOT_FOUND
ABORTED = grpc.StatusCode.ABORTED
UNKNOWN = grpc.StatusCode.UNKNOWN
OUT_OF_RANGE = grpc.StatusCode.OUT_OF_RANGE

SUPPORTED_ACCESS = [
    types.AccessModeType.SINGLE_NODE_WRITER,
    types.AccessModeType.SINGLE_NODE_READER_ONLY,
    types.AccessModeType.MULTI_NODE_READER_ONLY,
    # types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
    types.AccessModeType.MULTI_NODE_MULTI_WRITER,
]


def mount(src, tgt, flags=""):
    executable = cmd.mount
    flags = [f.strip() for f in flags.split(",")]
    if CONF.mock_vast:
        flags += "port=2049,nolock,vers=3".split(",")
    flags = list(filter(None, flags))
    if flags:
        executable = executable["-o", ",".join(flags)]
    try:
        executable['-v', src, tgt] & logger.pipe_info("mount >>")
    except ProcessExecutionError as exc:
        raise MountFailed(detail=exc.stderr, src=src, tgt=tgt, mount_options=flags)


def _validate_capabilities(capabilities):
    for capability in capabilities:
        if capability.access_mode.mode not in SUPPORTED_ACCESS:
            raise Abort(
                INVALID_ARGUMENT,
                f"Unsupported access mode: {capability.access_mode.mode} (use {SUPPORTED_ACCESS})",
            )

        if not capability.HasField("mount"):
            pass
        elif not capability.mount.fs_type:
            pass
        elif capability.mount.fs_type != "ext4":
            raise Abort(
                INVALID_ARGUMENT,
                f"Unsupported file system type: {capability.mount.fs_type}",
            )

class Instrumented:

    SILENCED = ["Probe", "NodeGetCapabilities"]

    @classmethod
    def logged(cls, func):

        method = func.__name__
        log = logger.debug if (method in cls.SILENCED) else logger.info

        parameters = inspect.signature(func).parameters
        required_params, non_required_params = map(
            set, separate(parameters, key=lambda k: parameters[k].default is inspect._empty)
        )
        vms_session_args = inspect.signature(get_vms_session).parameters.keys()
        required_params.discard("self")

        func = kwargs_resilient(func)

        @wraps(func)
        def wrapper(self, request, context):
            peer = context.peer()
            params = {fld.name: value for fld, value in request.ListFields()}
            # secrets are not logged and not the part of function signature.
            secrets = params.pop("secrets", {})
            missing_params = required_params - {"request", "context", "vms_session"} - set(params)

            log(f"{peer} >>> {method}:")

            if params:
                for line in pformat(params).splitlines():
                    log(f"({method})    {line}")

            if "vms_session" in required_params:
                # If secret exist and method signature requires `vms_session`
                # then `vms_session` with secret will be injected into function parameters
                params["vms_session"] = get_vms_session(**{k: secrets.get(k) for k in vms_session_args})
            elif "vms_session" in non_required_params:
                # Try to take vms_session from secret. Set None on error.
                try:
                    params["vms_session"] = get_vms_session(**{k: secrets.get(k) for k in vms_session_args})
                except LookupFieldError:
                    params["vms_session"] = None

            try:
                if missing_params:
                    msg = f'Missing required fields: {", ".join(sorted(missing_params))}'
                    logger.error(f"{peer} <<< {method}: {msg}")
                    raise Abort(INVALID_ARGUMENT, msg)

                ret = func(self, request=request, context=context, **params)
            except Abort as exc:
                logger.info(
                    f'{peer} <<< {method} ABORTED with {exc.code} ("{exc.message}")'
                )
                logger.debug("Traceback", exc_info=True)
                context.abort(exc.code, exc.message)
            except HTTPError as exc:
                reason = exc.response.reason
                status_code = exc.response.status_code
                text = exc.response.text.splitlines()[0]
                resource = exc.request.path_url
                logger.exception(f"Exception during {method}\n{exc.response.text}")
                context.abort(
                    UNKNOWN,
                    f"[{method}]. Unable to accomplish request to {resource}. {text}, <{reason}({status_code})>"
                )
            except TException as exc:
                # Any exception inherited from TException
                logger.exception(f"Exception during {method}")
                context.abort(UNKNOWN, f"[{method}]. {exc.render(color=False)}")
            except Exception as exc:
                logger.exception(f"Exception during {method}")
                text = str(exc)
                context.abort(UNKNOWN, f"[{method}]: {text}")
            if ret:
                log(f"{peer} <<< {method}:")
                for line in pformat(ret).splitlines():
                    log(f"    {line}")
            log(f"{peer} --- {method}: Done")
            return ret

        return wrapper

    @classmethod
    def __init_subclass__(cls):
        for name, _ in inspect.getmembers(cls.__base__, inspect.isfunction):
            if name.startswith("_"):
                continue
            func = getattr(cls, name)
            setattr(cls, name, cls.logged(func))
        super().__init_subclass__()


################################################################
#
# Identity
#
################################################################


class CsiIdentity(csi_grpc.IdentityServicer, Instrumented):
    def __init__(self):
        self.capabilities = []
        self.controller = None
        self.node = None

    def GetPluginInfo(self, request, context):
        return types.InfoResp(
            name=CONF.plugin_name,
            vendor_version=CONF.plugin_version,
        )

    def GetPluginCapabilities(self, request, context):
        return types.CapabilitiesResp(
            capabilities=[
                types.Capability(service=types.Service(type=cap))
                for cap in self.capabilities
            ]
        )

    def Probe(self, request, context):
        return types.ProbeRespOK



################################################################
#
# Controller
#
################################################################


class CsiController(csi_grpc.ControllerServicer, Instrumented):

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

    def ControllerGetCapabilities(self):
        return types.CtrlCapabilityResp(
            capabilities=[
                types.CtrlCapability(rpc=types.CtrlCapability.RPC(type=rpc))
                for rpc in self.CAPABILITIES
            ]
        )

    def ValidateVolumeCapabilities(
        self,
        vms_session,
        context,
        volume_id,
        volume_capabilities,
        volume_context=None,
        parameters=None,
    ):
        if not vms_session.get_quota(volume_id):
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
        _validate_capabilities(volume_capabilities)
        parameters = parameters or dict()

        try:
            mount_capability = next(cap for cap in volume_capabilities if cap.HasField("mount"))
            mount_flags = mount_capability.mount.mount_flags
            mount_options = ",".join(mount_flags)
            # normalize mount options (remove spaces, brackets etc)
            mount_options = ",".join(re.sub(r"[\[\]]", "", mount_options).replace(",", " ").split())
        except StopIteration:
            mount_options = ""
        # check if list of provided access modes contains read-write mode
        rw_access_modes = [types.AccessModeType.SINGLE_NODE_WRITER, types.AccessModeType.MULTI_NODE_MULTI_WRITER]
        rw_access_mode = any(
            cap.access_mode.mode in rw_access_modes for cap in volume_capabilities if cap.HasField("access_mode")
        )
        # Take appropriate builder for volume, snapshot or test builder
        if CONF.mock_vast:
            root_export = volume_name_fmt = view_policy = vip_pool_name = vip_pool_fqdn = mount_options = qos_policy = ""
            builder = TestVolumeBuilder

        else:
            if not (root_export := parameters.get("root_export")):
                raise MissingParameter(param="root_export")
            if not (view_policy := parameters.get("view_policy")):
                raise MissingParameter(param="view_policy")

            vip_pool_fqdn = parameters.get("vip_pool_fqdn")
            vip_pool_name = parameters.get("vip_pool_name")
            if vip_pool_name and vip_pool_fqdn:
                raise Abort(
                    INVALID_ARGUMENT,
                    "vip_pool_name and vip_pool_fqdn are mutually exclusive. Provide one of them."
                )
            elif not (vip_pool_name or vip_pool_fqdn):
                if not CONF.use_local_ip_for_mount:
                    raise Abort(
                        INVALID_ARGUMENT,
                        "either vip_pool_name, vip_pool_fqdn or use_local_ip_for_mount must be provided."
                    )
                elif not is_valid_ip(CONF.use_local_ip_for_mount):
                    raise Abort(INVALID_ARGUMENT, f"Local IP address: {CONF.use_local_ip_for_mount} is invalid")
            volume_name_fmt = parameters.get("volume_name_fmt", CONF.name_fmt)
            qos_policy = parameters.get("qos_policy")

            if not volume_content_source:
                builder = EmptyVolumeBuilder

            elif volume_content_source.snapshot.snapshot_id:
                builder = VolumeFromSnapshotBuilder

            elif volume_content_source.volume.volume_id:
                builder = VolumeFromVolumeBuilder

            else:
                raise ValueError(
                    "Invalid condition. Either volume_content_source"
                    " or test environment variable should be provided"
                )

        # Create volume, volume from snapshot or mount local path (for testing purposes)
        # depends on chosen builder.
        builder = builder(
            vms_session=vms_session,
            configuration=CONF,
            name=name,
            rw_access_mode=rw_access_mode,
            capacity_range=capacity_range,
            pvc_name=parameters.get("csi.storage.k8s.io/pvc/name"),
            pvc_namespace=parameters.get("csi.storage.k8s.io/pvc/namespace"),
            volume_content_source=volume_content_source,
            ephemeral_volume_name=ephemeral_volume_name,
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            mount_options=mount_options,
            qos_policy=qos_policy,
        )
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
                vms_session.delete_folder(path, tenant_id)
                return  # Successfully deleted. Prevent using local mounting
            except OperationNotSupported as exc:
                logger.debug(f"Trash API not available {exc}")
                CONF.avoid_trash_api.reset()

        logger.info(f"Use local mounting to delete {path}")
        path = local.path(path)
        volume_id = path.name
        assert CONF.deletion_view_policy, (
            "Ensure that deletionViewPolicy is properly "
            "configured in your Helm configuration to perform local volume deletion."
        )
        view_policy = vms_session.get_view_policy(policy_name=CONF.deletion_view_policy)
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
            nfs_server_ip = vms_session.get_vip(CONF.deletion_vip_pool, view_policy.tenant_id)

        logger.info(f"Creating temporary base view.")
        with vms_session.temp_view(path.dirname, view_policy.id, view_policy.tenant_id) as base_view:
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
                    cmd.umount['-v', tmpdir] & logger.pipe_info("umount >>", retcode=None)  # don't fail if not mounted
                os.remove(tmpdir['.csi-unmounted'])  # will fail if still mounted somehow
                os.rmdir(tmpdir)  # will fail if not empty directory

    def DeleteVolume(self, vms_session, volume_id):
        vms_session.ensure_snapshot_stream_deleted(f"strm-{volume_id}")
        if quota := vms_session.get_quota(volume_id):
            # this is a check we have to do until Vast provides access to orphaned snapshots (ORION-135599)
            might_use_trash_folder = not CONF.dont_use_trash_api
            if might_use_trash_folder and vms_session.has_snapshots(quota.path):
                raise Exception(f"Unable to delete {volume_id} as it holds snapshots")
            try:
                self._delete_data_from_storage(vms_session, quota.path, quota.tenant_id)
            except OSError as exc:
                if 'not empty' not in str(exc):
                    raise
                if snaps := vms_session.has_snapshots(quota.path):
                    # this is expected when the volume has snapshots
                    logger.info(f"{quota.path} will remain due to remaining {len(snaps)} snapshots")
                else:
                    raise
            logger.info(f"Data removed: {quota.path}")

            vms_session.delete_view_by_path(quota.path)
            logger.info(f"View removed: {quota.path}")

            vms_session.delete_quota(quota.id)
            logger.info(f"Quota removed: {quota.id}")

        logger.info(f"Removed volume: {volume_id}")
        return types.DeleteResp()

    def ControllerPublishVolume(
        self, vms_session, node_id, volume_id, volume_capability, volume_context=None
    ):
        volume_context = volume_context or dict()
        _validate_capabilities([volume_capability])

        if CONF.mock_vast:
            root_export = CONF.sanity_test_nfs_export
        else:
            root_export = local.path(volume_context["root_export"])
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
        elif vip_pool_name or CONF.mock_vast:
            nfs_server_ip = vms_session.get_vip(vip_pool_name=vip_pool_name)
        else:
            nfs_server_ip = CONF.use_local_ip_for_mount
            assert nfs_server_ip, f"{nfs_server_ip=}"
            logger.info(f"Using local IP for mount: {nfs_server_ip}")

        return types.CtrlPublishResp(
            publish_context=dict(
                export_path=export_path,
                nfs_server_ip=nfs_server_ip,
            )
        )

    def ControllerUnpublishVolume(self, node_id, volume_id):
        return types.CtrlUnpublishResp()

    def ControllerExpandVolume(self, vms_session, volume_id, capacity_range):
        requested_capacity = capacity_range.required_bytes

        if not (quota := vms_session.get_quota(volume_id)):
            raise Abort(NOT_FOUND, f"Not found quota with id: {volume_id}")

        existing_capacity = quota.hard_limit
        if requested_capacity <= existing_capacity:
            capacity_bytes = existing_capacity
        else:
            try:
                vms_session.update_quota(
                    quota_id=quota.id, data=dict(hard_limit=requested_capacity)
                )
            except ApiError as exc:
                raise Abort(OUT_OF_RANGE, f"Failed updating quota {quota.id}: {exc}")
            capacity_bytes = requested_capacity

        return types.CtrlExpandResp(
            capacity_bytes=capacity_bytes,
            node_expansion_required=False,
        )

    def CreateSnapshot(self, vms_session, source_volume_id, name, parameters=None):

        parameters = parameters or dict()
        volume_id = source_volume_id
        if not (quota := vms_session.get_quota(volume_id)):
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
                snap = vms_session.ensure_snapshot(snapshot_name=snapshot_name, path=path, tenant_id=tenant_id)
            except ApiError as exc:
                handled = False
                if exc.response.status_code == 400:
                    try:
                        [(k, [v])] = exc.response.json().items()
                    except (ValueError, JSONDecodeError):
                        pass
                    else:
                        if (k, v) == ("name", "This field must be unique."):
                            snap = vms_session.get_snapshot(snapshot_name=snapshot_name)
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
                snapshot_id=str(snap.id),
                source_volume_id=volume_id,
                creation_time=string_to_proto_timestamp(snap.created),
                ready_to_use=True,
            )

        return types.CreateSnapResp(snapshot=snp)

    def DeleteSnapshot(self, vms_session, snapshot_id):
        if CONF.mock_vast:
            CONF.fake_snapshot_store[snapshot_id].delete()
        else:
            snapshot = vms_session.get_snapshot(snapshot_id=snapshot_id)
            vms_session.delete_snapshot(snapshot_id)
            if vms_session.get_quotas_by_path(snapshot.path):
                pass  # quotas still exist
            elif vms_session.has_snapshots(snapshot.path):
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


class CsiNode(csi_grpc.NodeServicer, Instrumented):

    CAPABILITIES = [
        # types.NodeCapabilityType.STAGE_UNSTAGE_VOLUME,
        types.NodeCapabilityType.GET_VOLUME_STATS,
    ]

    @cached_property
    def controller(self):
        return CsiController()

    def NodeGetCapabilities(self):
        return types.NodeCapabilityResp(
            capabilities=[
                types.NodeCapability(rpc=types.NodeCapability.RPC(type=rpc))
                for rpc in self.CAPABILITIES
            ]
        )

    def NodePublishVolume(
        self,
        vms_session,
        volume_id,
        target_path,
        volume_capability=None,
        publish_context=None,
        readonly=False,
        volume_context=None,
    ):
        volume_context = volume_context or dict()
        if (
            is_ephemeral := volume_context
            and volume_context.get("csi.storage.k8s.io/ephemeral") == "true"
        ):
            from .quantity import parse_quantity

            eph_volume_name_fmt = volume_context.get("eph_volume_name_fmt", CONF.name_fmt)
            if "size" in volume_context:
                required_bytes = int(parse_quantity(volume_context["size"]))
                capacity_range = Bunch(required_bytes=required_bytes)
            else:
                capacity_range = None
            pod_uid = volume_context["csi.storage.k8s.io/pod.uid"]
            pod_name = volume_context["csi.storage.k8s.io/pod.name"]
            pod_namespace = volume_context["csi.storage.k8s.io/pod.namespace"]
            eph_volume_name = eph_volume_name_fmt.format(
                namespace=pod_namespace, name=pod_name, id=pod_uid
            )
            self.controller.CreateVolume.__wrapped__(
                self.controller,
                vms_session=vms_session,
                name=volume_id,
                volume_capabilities=[],
                ephemeral_volume_name=eph_volume_name,
                capacity_range=capacity_range,
                parameters=volume_context
            )
            resp = self.controller.ControllerPublishVolume.__wrapped__(
                self.controller,
                vms_session=vms_session,
                node_id=CONF.node_id,
                volume_id=volume_id,
                volume_capability=volume_capability,
                volume_context=volume_context,
            )
            publish_context = resp.publish_context
        elif not volume_capability:
            raise Abort(INVALID_ARGUMENT, "missing 'volume_capability'")

        if not publish_context:
            assert not CONF.attach_required, "missing 'publish_context' when attach_required is enabled"
            logger.info("attach_required is disabled, obtaining publish context")
            resp = self.controller.ControllerPublishVolume.__wrapped__(
                self.controller,
                vms_session=vms_session,
                node_id=CONF.node_id,
                volume_id=volume_id,
                volume_capability=volume_capability,
                volume_context=volume_context,
            )
            publish_context = resp.publish_context

        nfs_server_ip = publish_context["nfs_server_ip"]

        schema = "1" if not volume_context else volume_context.get("schema", "1")
        if schema == "2":
            export_path = volume_context["export_path"]
        else:
            export_path = publish_context["export_path"]
        mount_spec = f"{nfs_server_ip}:{export_path}"

        _validate_capabilities([volume_capability])
        target_path = local.path(target_path)

        if not target_path.is_dir():
            pass
        elif found_mount := get_mount(target_path):
            opts = set(found_mount.opts.split(","))
            is_readonly = "ro" in opts
            if found_mount.device != mount_spec:
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
        payload = dict(volume_id=volume_id, is_ephemeral=is_ephemeral)
        if is_ephemeral:
            payload["vms_session"] = vms_session.serialize(salt=volume_id.encode())
        with meta_file.open("w") as f:
            json.dump(payload, f)
        os.chmod(meta_file, 0o600)
        logger.info(f"created: {target_path}")

        flags = ["ro"] if readonly else []
        if volume_capability.mount.mount_flags:
            flags += volume_capability.mount.mount_flags
        else:
            flags += normalize_mount_options(volume_context.get("mount_options", ""))
        try:
            mount(mount_spec, target_path, flags=",".join(flags))
            logger.info(f"mounted: {target_path} flags: {flags}")
        except Exception:
            meta_file.delete()
            raise

        return types.NodePublishResp()

    def NodeUnpublishVolume(self, volume_id, target_path, vms_session=None):
        target_path = local.path(target_path)

        if not target_path.exists():
            logger.info(f"{target_path} does not exist - no need to remove")
        else:
            # make sure we're really unmounted before we delete anything
            for i in range(CONF.unmount_attempts):
                if not get_mount(target_path):
                    logger.info(f"{target_path} is not mounted")
                    break
                try:
                    local.cmd.umount(target_path)
                except ProcessExecutionError as exc:
                    if "not mounted" in exc.stderr:
                        logger.info(f"umount failed - {target_path} is not mounted (race?)")
                        break
                    raise
            else:
                raise Abort(
                    UNKNOWN,
                    f"Stuck in unmount loop of {target_path} too many times ({CONF.unmount_attempts})",
                )

            logger.info(f"Deleting {target_path}")
            if target_path[".vast-csi-meta"].exists():
                with target_path[".vast-csi-meta"].open("r") as f:
                    meta = json.load(f)
                if meta.get("is_ephemeral"):
                    if vms_session_data := meta.get("vms_session"):
                        vms_session = VmsSession.deserialize(
                            salt=volume_id.encode(), encrypted_data=vms_session_data
                        )
                    elif not vms_session:
                        raise Abort(
                            FAILED_PRECONDITION,
                            "Ephemeral Volume provisioning requires "
                            "configuring a global VMS credentials secret or nodePublishSecretRef secret reference."
                        )
                    self.controller.DeleteVolume.__wrapped__(
                        self.controller, vms_session=vms_session, volume_id=meta["volume_id"]
                    )

            if target_path[".vast-csi-meta"].exists():
                os.remove(target_path[".vast-csi-meta"])
            os.rmdir(target_path)  # don't use plumbum's .delete to avoid the dangerous rmtree
            logger.info(f"{target_path} removed successfully")
        return types.NodeUnpublishResp()

    def NodeGetInfo(self):
        return types.NodeInfoResp(node_id=CONF.node_id)

    def NodeGetVolumeStats(self, volume_id, volume_path):
        if not os.path.ismount(volume_path):
            raise Abort(NOT_FOUND, f"{volume_path} is not a mountpoint")
        # See http://man7.org/linux/man-pages/man2/statfs.2.html for details.
        fstats = os.statvfs(volume_path)
        return types.VolumeStatsResp(
            usage=[
                types.VolumeUsage(
                    unit=types.UsageUnit.BYTES,
                    available=fstats.f_bavail * fstats.f_bsize,
                    total=fstats.f_blocks * fstats.f_bsize,
                    used=(fstats.f_blocks - fstats.f_bfree) * fstats.f_bsize,
                ),
                types.VolumeUsage(
                    unit=types.UsageUnit.INODES,
                    available=fstats.f_ffree,
                    total=fstats.f_files,
                    used=fstats.f_files - fstats.f_ffree,
                )
            ]
        )


class CosiIdentity(cosi_grpc.IdentityServicer, Instrumented):

    def DriverGetInfo(self, request, context):
        return types.DriverGetInfoResp(name=CONF.plugin_name)


class CosiProvisioner(cosi_grpc.ProvisionerServicer, Instrumented):

    def DriverCreateBucket(self, vms_session, name, parameters):
        if (root_export := parameters.pop("root_export", None)) is None:
            raise MissingParameter(param="root_export")
        if not (vip_pool_name := parameters.pop("vip_pool_name", None)):
            raise MissingParameter(param="vip_pool_name")
        scheme = parameters.pop("scheme", "http")

        if CONF.truncate_volume_name:
            name = name[:CONF.truncate_volume_name]  # crop to Vast's max-length

        uid = randint(50000, 60000)
        vms_session.ensure_user(uid=uid, name=name, allow_create_bucket=True)
        view = vms_session.ensure_s3view(bucket_name=name, root_export=root_export, **parameters)
        port = 443 if scheme == "https" else 80
        vip = vms_session.get_vip(vip_pool_name=vip_pool_name, tenant_id=view.tenant_id)
        # bucket_id contains bucket name and endpoint
        # should be smth like test-bucket-caf9e0d0-0b9a-4b5e-8b0a-9b0brb0b4c0c@1@https://172.0.0.1:443
        return types.DriverCreateBucketResp(
            bucket_id=f"{name}@{view.tenant_id}@{scheme}://{vip}:{port}",
            bucket_info=types.Protocol(
                s3=types.S3(
                    region="N/A",
                    signature_version=types.S3SignatureVersion.UnknownSignature
                )
            )
        )

    def DriverDeleteBucket(self, vms_session, bucket_id, delete_context):
        bucket_id, _, _ = bucket_id.split('@')
        if view := vms_session.get_view(bucket=bucket_id):
            vms_session.delete_folder(view.path, view.tenant_id)
            vms_session.delete_view_by_id(view.id)
        if user := vms_session.get_user(bucket_id):
            vms_session.delete_user(user.id)
        return types.DriverDeleteBucketResp()

    def DriverGrantBucketAccess(self, vms_session, bucket_id, name):
        bucket_id, _, endpoint = bucket_id.split('@')
        user = vms_session.get_user(bucket_id)
        creds = vms_session.generate_access_key(user.id)
        credentials = dict(
            s3=types.CredentialDetails(
                secrets={"accessKeyID": creds.access_key, "accessSecretKey": creds.secret_key, "endpoint": endpoint}
            )
        )
        return types.DriverGrantBucketAccessResp(
            account_id=creds.access_key,
            credentials=credentials
        )

    def DriverRevokeBucketAccess(self, vms_session, bucket_id, account_id):
        bucket_id, _, _ = bucket_id.split('@')
        if user := vms_session.get_user(bucket_id):
            vms_session.delete_access_key(user.id, account_id)
        return types.DriverRevokeBucketAccessResp()


################################################################
#
# Entrypoint
#
################################################################


def serve():
    patch_traceback_format()
    global CONF
    CONF = Config()
    init_logging(level=CONF.log_level)
    logger.info("%s: %s (%s)", CONF.plugin_name, CONF.plugin_version, CONF.git_commit)

    if not CONF.ssl_verify:
        import urllib3

        urllib3.disable_warnings()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=CONF.worker_threads))

    identity = CsiIdentity()
    csi_grpc.add_IdentityServicer_to_server(identity, server)

    identity.capabilities.append(types.ExpansionType.ONLINE)

    if CONF.mode in {CONTROLLER, CONTROLLER_AND_NODE}:
        identity.controller = CsiController()
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_grpc.add_ControllerServicer_to_server(identity.controller, server)
        CONF.fake_quota_store.mkdir()
        CONF.fake_snapshot_store.mkdir()

    if CONF.mode in {NODE, CONTROLLER_AND_NODE}:
        identity.node = CsiNode()
        csi_grpc.add_NodeServicer_to_server(identity.node, server)

    # COSI
    if CONF.mode == COSI_PLUGIN:
        cosi_identity = CosiIdentity()
        cosi_grpc.add_IdentityServicer_to_server(cosi_identity, server)

        cosi_provisioner = CosiProvisioner()
        cosi_grpc.add_ProvisionerServicer_to_server(cosi_provisioner, server)

    server.add_insecure_port(CONF.endpoint)
    server.start()

    logger.info(f"Server started as '{CONF.mode}', listening on {CONF.endpoint}, spawned threads {CONF.worker_threads}")
    server.wait_for_termination()
