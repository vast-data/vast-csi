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
import socket
from concurrent import futures
from functools import wraps
from pprint import pformat
from datetime import datetime
import inspect
from uuid import uuid4
import psutil

import json
from json import JSONDecodeError
from plumbum import local, ProcessExecutionError
from plumbum.typed_env import TypedEnv
import grpc

from easypy.tokens import Token, ROUNDROBIN, RANDOM, CONTROLLER_AND_NODE, CONTROLLER, NODE
from easypy.misc import kwargs_resilient, at_least
from easypy.caching import cached_property
from easypy.collections import shuffled
from easypy.exceptions import TException
from easypy.bunch import Bunch

from . logging import logger, init_logging
from . utils import patch_traceback_format, RESTSession, ApiError, HTTPError
from . import csi_pb2_grpc
from .csi_pb2_grpc import ControllerServicer, NodeServicer, IdentityServicer
from . import csi_types as types


LOAD_BALANCING_STRATEGIES = {ROUNDROBIN, RANDOM}


class Config(TypedEnv):

    class Path(TypedEnv.Str):
        convert = staticmethod(local.path)

    plugin_name, plugin_version, git_commit = open("version.info").read().strip().split()
    plugin_name = TypedEnv.Str("X_CSI_PLUGIN_NAME", default=plugin_name)

    controller_root_mount = Path("X_CSI_CTRL_ROOT_MOUNT", default=local.path("/csi-volumes"))
    mock_vast = TypedEnv.Bool("X_CSI_MOCK_VAST", default=False)
    nfs_server = TypedEnv.Str("X_CSI_NFS_SERVER", default="127.0.0.1")
    root_export = Path("X_CSI_NFS_EXPORT", default=local.path("/k8s"))
    log_level = TypedEnv.Str("X_CSI_LOG_LEVEL", default="info")
    csi_sanity_test = TypedEnv.Bool("X_CSI_SANITY_TEST", default=False)
    node_id = TypedEnv.Str("X_CSI_NODE_ID", default=socket.getfqdn())

    vms_host = TypedEnv.Str("X_CSI_VMS_HOST", default="vast")
    vip_pool_name = TypedEnv.Str("X_CSI_VIP_POOL_NAME", default="k8s")
    vms_user = TypedEnv.Str("X_CSI_VMS_USER", default="admin")
    vms_password = TypedEnv.Str("X_CSI_VMS_PASSWORD", default="admin")
    ssl_verify = TypedEnv.Bool("X_CSI_DISABLE_VMS_SSL_VERIFICATION", default=False)
    volume_name_fmt = TypedEnv.Str("X_CSI_VOLUME_NAME_FMT", default="csi:{namespace}:{name}:{id}")
    snapshot_name_fmt = TypedEnv.Str("X_CSI_SNAPSHOT_NAME_FMT", default="{name}")
    eph_volume_name_fmt = TypedEnv.Str("X_CSI_EPHEMERAL_VOLUME_NAME_FMT", default="csi:{namespace}:{name}:{id}")

    _mount_options = TypedEnv.Str("X_CSI_MOUNT_OPTIONS", default="")  # For example: "port=2049,nolock,vers=3"

    @property
    def mount_options(self):
        s = self._mount_options.strip()
        return list({p for p in s.split(',') if p})

    _load_balancing = TypedEnv.Str("X_CSI_LB_STRATEGY", default="roundrobin")
    _mode = TypedEnv.Str("CSI_MODE", default="controller_and_node")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default='unix:///var/run/csi.sock')

    @property
    def load_balancing(self):
        lb = Token(self._load_balancing.upper())
        if lb not in LOAD_BALANCING_STRATEGIES:
            raise Exception(f"invalid load balancing strategy: {lb} (use {'|'.join(LOAD_BALANCING_STRATEGIES)})")
        return lb

    @property
    def mode(self):
        mode = Token(self._mode.upper())
        assert mode in {CONTROLLER_AND_NODE, CONTROLLER, NODE}, f"invalid mode: {mode}"
        return mode

    @property
    def endpoint(self):
        return self._endpoint.strip("tcp://")


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
    # types.AccessModeType.SINGLE_NODE_READER_ONLY,
    # types.AccessModeType.MULTI_NODE_READER_ONLY,
    # types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
    types.AccessModeType.MULTI_NODE_MULTI_WRITER,
]


class MountFailed(TException):
    template = "Mounting {src} failed"


def mount(src, tgt, flags=""):
    cmd = local.cmd.mount
    flags = [f.strip() for f in flags.split(",")]
    if CONF.mock_vast:
        flags += "port=2049,nolock,vers=3".split(",")
    flags = list(filter(None, flags))
    if flags:
        cmd = cmd["-o", ",".join(flags)]
    try:
        cmd[src, tgt] & logger.pipe_info("mount >>")
    except ProcessExecutionError as exc:
        if exc.retcode == 32:
            raise MountFailed(detail=exc.stderr, src=src, tgt=tgt)
        raise


def _validate_capabilities(capabilities):
    for capability in capabilities:
        if capability.access_mode.mode not in SUPPORTED_ACCESS:
            raise Abort(
                INVALID_ARGUMENT,
                f'Unsupported access mode: {capability.access_mode.mode} (use {SUPPORTED_ACCESS})')

        if not capability.HasField('mount'):
            pass
        elif not capability.mount.fs_type:
            pass
        elif capability.mount.fs_type != "ext4":
            raise Abort(
                INVALID_ARGUMENT,
                f'Unsupported file system type: {capability.mount.fs_type}')


class Abort(Exception):

    @property
    def code(self):
        return self.args[0]

    @property
    def message(self):
        return self.args[1]


class Instrumented():

    SILENCED = ["Probe", "NodeGetCapabilities"]

    @classmethod
    def logged(cls, func):

        method = func.__name__
        log = logger.debug if (method in cls.SILENCED) else logger.info

        parameters = inspect.signature(func).parameters
        required_params = {
            name for name, p in parameters.items() if p.default is p.empty}
        required_params.discard("self")

        func = kwargs_resilient(func)

        @wraps(func)
        def wrapper(self, request, context):
            peer = context.peer()
            params = {fld.name: value for fld, value in request.ListFields()}
            missing = required_params - {"request", "context"} - set(params)

            log(f"{peer} >>> {method}:")

            if params:
                for line in pformat(params).splitlines():
                    log(f"    {line}")

            try:
                if missing:
                    msg = f'Missing required fields: {", ".join(sorted(missing))}'
                    logger.error(f"{peer} <<< {method}: {msg}")
                    raise Abort(INVALID_ARGUMENT, msg)

                ret = func(self, request=request, context=context, **params)
            except Abort as exc:
                logger.info(f'{peer} <<< {method} ABORTED with {exc.code} ("{exc.message}")')
                logger.debug("Traceback", exc_info=True)
                context.abort(exc.code, exc.message)
            except Exception as exc:
                err_key = f"<{uuid4()}>"
                logger.exception(f"Exception during {method} ({err_key}): {type(exc)}")
                context.abort(UNKNOWN, f"Exception during {method}: {err_key}")
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


class Identity(IdentityServicer, Instrumented):

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
                for cap in self.capabilities])

    def Probe(self, request, context):
        if self.node:
            return types.ProbeRespOK
        elif CONF.mock_vast:
            return types.ProbeRespOK
        elif self.controller:
            try:
                self.controller.get_vip()
            except ApiError as exc:
                raise Abort(FAILED_PRECONDITION, str(exc))
            return types.ProbeRespOK
        else:
            return types.ProbeRespNotReady


################################################################
#
# Controller
#
################################################################


class Controller(ControllerServicer, Instrumented):

    CAPABILITIES = [
        types.CtrlCapabilityType.CREATE_DELETE_VOLUME,
        types.CtrlCapabilityType.PUBLISH_UNPUBLISH_VOLUME,
        types.CtrlCapabilityType.LIST_VOLUMES,
        types.CtrlCapabilityType.EXPAND_VOLUME,
        types.CtrlCapabilityType.CREATE_DELETE_SNAPSHOT,
        types.CtrlCapabilityType.LIST_SNAPSHOTS,
        # types.CtrlCapabilityType.GET_CAPACITY,
        # types.CtrlCapabilityType.CLONE_VOLUME,
        # types.CtrlCapabilityType.PUBLISH_READONLY,
    ]

    mock_vol_db = local.path("/tmp/volumes")
    mock_snp_db = local.path("/tmp/snapshots")

    @cached_property
    def vms_session(self):
        auth = CONF.vms_user, CONF.vms_password
        return RESTSession(
            base_url=f"https://{CONF.vms_host}/api",
            auth=auth, ssl_verify=CONF.ssl_verify)

    _vip_round_robin_idx = -1

    def get_vip(self):
        if CONF.mock_vast:
            return CONF.nfs_server

        vips = [vip for vip in self.vms_session.vips() if vip.vippool == CONF.vip_pool_name]
        if not vips:
            raise Exception(f"No vips in pool {CONF.vip_pool_name}")

        if CONF.load_balancing == ROUNDROBIN:
            self._vip_round_robin_idx = (self._vip_round_robin_idx + 1) % len(vips)
            vip = vips[self._vip_round_robin_idx]
        elif CONF.load_balancing == RANDOM:
            vip = shuffled(vips)[0]
        else:
            raise Exception(f"Invalid load_balancing mode: '{CONF.load_balancing}'")

        logger.info(f"Using {CONF.load_balancing} - chose {vip.title}, currently connected to {vip.cnode}")
        return vip.ip

    def get_quota(self, volume_id):
        quotas = self.vms_session.quotas(path__contains=str(CONF.root_export[volume_id]))
        if not quotas:
            return
        elif len(quotas) > 1:
            names = ", ".join(sorted(q.name for q in quotas))
            raise Exception(f"Too many quotas on {volume_id}: {names}")
        else:
            return quotas[0]

    @cached_property
    def root_mount(self):
        target_path = CONF.controller_root_mount
        if not target_path.exists():
            target_path.mkdir()
            target_path["NOT_MOUNTED"].touch()
            logger.info(f"created successfully: {target_path}")

        if target_path["NOT_MOUNTED"].exists():
            nfs_server = self.get_vip()
            mount_spec = f"{nfs_server}:{CONF.root_export}"
            mount(mount_spec, target_path, flags=",".join(CONF.mount_options))
            logger.info(f"mounted successfully: {target_path}")

        return target_path

    def ControllerGetCapabilities(self):
        return types.CtrlCapabilityResp(capabilities=[
            types.CtrlCapability(rpc=types.CtrlCapability.RPC(type=rpc))
            for rpc in self.CAPABILITIES])

    def ValidateVolumeCapabilities(self, context, volume_id, volume_capabilities, volume_context=None, parameters=None):
        vol = self.root_mount[volume_id]
        if not vol.exists():
            raise Abort(NOT_FOUND, f'Volume {volume_id} does not exist')

        try:
            _validate_capabilities(volume_capabilities)
        except Abort as exc:
            return types.ValidateResp(message=exc.message)

        confirmed = types.ValidateResp.Confirmed(
            volume_context=volume_context,
            volume_capabilities=volume_capabilities,
            parameters=parameters)

        return types.ValidateResp(confirmed=confirmed)

    def ListVolumes(self, starting_token=None, max_entries=None):

        if starting_token == "invalid-token":
            raise Abort(ABORTED, "Invalid starting_token")

        fields = {'entries': []}

        if CONF.mock_vast:
            starting_inode = int(starting_token) if starting_token else 0
            vols = (d for d in os.scandir(self.root_mount) if d.is_dir())
            vols = sorted(vols, key=lambda d: d.inode())
            logger.info(f"Got {len(vols)} volumes in {self.root_mount}")
            start_idx = 0

            logger.info(f"Skipping to {starting_inode}")
            for start_idx, d in enumerate(vols):
                if d.inode() > starting_inode:
                    break

            del vols[:start_idx]

            remain = 0
            if max_entries:
                remain = at_least(0, len(vols) - max_entries)
                vols = vols[:max_entries]

            if remain:
                fields['next_token'] = str(vols[-1].inode())

            fields['entries'] = [types.ListResp.Entry(
                volume=self._to_mock_volume(vol.name))
                for vol in vols]

            return types.ListResp(**fields)

        else:
            if starting_token:
                ret = self.vms_session.quotas(path__contains=CONF.root_export, page_size=max_entries)
            else:
                ret = self.vms_session.get(starting_token)
            return types.ListResp(next_token=ret.next_token, entries=[types.ListResp.Entry(snapshot=types.Volume(
                capacity_bytes=quota.hard_limit, volume_id=self._to_volume_id(quota.path),
                volume_context=dict(quota_id=str(quota.id))
            )) for quota in ret.results])

    def _to_mock_volume(self, vol_id):
        assert CONF.mock_vast
        vol_dir = self.root_mount[vol_id]
        logger.info(f"{vol_dir}")
        if not vol_dir.is_dir():
            logger.info(f"{vol_dir} is not dir")
            return
        with self.mock_vol_db[vol_id].open("rb") as f:
            vol = types.Volume()
            vol.ParseFromString(f.read())
            return vol

    def CreateVolume(
            self, name, volume_capabilities, capacity_range=None, parameters=None, volume_content_source=None,
            ephemeral_volume_name=None
    ):
        _validate_capabilities(volume_capabilities)

        if not volume_content_source:
            pass
        elif not CONF.mock_vast:
            raise Abort(INVALID_ARGUMENT, "Creating volumes from snapshots is currently not supported")
        elif not self.mock_snp_db[volume_content_source.snapshot.snapshot_id].exists():
            raise Abort(NOT_FOUND, f"Source snapshot does not exist: {volume_content_source.snapshot.snapshot_id}")

        volume_id = name
        if ephemeral_volume_name:
            assert not parameters, "Can't provide parameters for ephemeral volume"
            volume_name = ephemeral_volume_name
        elif parameters:
            pvc_name = parameters.get("csi.storage.k8s.io/pvc/name")
            pvc_namespace = parameters.get("csi.storage.k8s.io/pvc/namespace")
            if pvc_namespace and pvc_name:
                volume_name = CONF.volume_name_fmt.format(namespace=pvc_namespace, name=pvc_name, id=volume_id)
        else:
            volume_name = f"csi-{volume_id}"

        if len(volume_name) > 64:
            logger.warning(f"cropping volume name ({len(volume_name)}>64): {volume_name}")
            volume_name = volume_name[:64]  # crop to Vast's max-length

        requested_capacity = capacity_range.required_bytes if capacity_range else 0
        existing_capacity = 0
        volume_context = {}

        if CONF.mock_vast:
            volume = self._to_mock_volume(volume_id)
            if volume:
                existing_capacity = volume.capacity_bytes
        else:
            quota = self.get_quota(volume_id)
            if quota:
                existing_capacity = quota.hard_limit

        if not existing_capacity:
            pass
        elif existing_capacity != requested_capacity:
            raise Abort(
                ALREADY_EXISTS,
                "Volume already exists with different capacity than requested"
                f"({existing_capacity})")

        if CONF.mock_vast:
            vol_dir = self.root_mount[volume_id]
            vol_dir.mkdir()
        else:
            data = dict(
                create_dir=True,
                name=volume_name,
                path=str(CONF.root_export[volume_id]),
            )
            if requested_capacity:
                data.update(hard_limit=requested_capacity)
            quota = self.vms_session.post("quotas", data=data)
            volume_context.update(quota_id=quota.id)

        volume = types.Volume(
            capacity_bytes=requested_capacity, volume_id=volume_id,
            volume_context={k: str(v) for k, v in volume_context.items()})

        if CONF.mock_vast:
            with self.mock_vol_db[volume_id].open("wb") as f:
                f.write(volume.SerializeToString())

        return types.CreateResp(volume=volume)

    def DeleteVolume(self, volume_id):
        vol_dir = self.root_mount[volume_id]
        vol_dir.delete()

        if not CONF.mock_vast:
            quota = self.get_quota(volume_id)
            if quota:
                self.vms_session.delete(f"quotas/{quota.id}")
                logger.info(f"Quota removed: {quota.id}")
        else:
            self.mock_vol_db[volume_id].delete()

        logger.info(f"Removed volume: {vol_dir}")
        return types.DeleteResp()

    def GetCapacity(self):
        cap = os.statvfs(self.root_mount).f_favail
        return types.CapacityResp(available_capacity=cap)

    def ControllerPublishVolume(self, node_id, volume_id, volume_capability):
        _validate_capabilities([volume_capability])

        found = bool(self._to_mock_volume(volume_id) if CONF.mock_vast else self.get_quota(volume_id))
        if not found:
            raise Abort(NOT_FOUND, f"Unknown volume: {volume_id}")

        if CONF.csi_sanity_test and CONF.node_id != node_id:
            # for a test that tries to fake a non-existent node
            raise Abort(NOT_FOUND, f"Unknown volume: {node_id}")

        nfs_server_ip = self.get_vip()

        return types.CtrlPublishResp(
            publish_context=dict(
                export_path=str(CONF.root_export),
                nfs_server_ip=nfs_server_ip,
            ))

    def ControllerUnpublishVolume(self, node_id, volume_id):
        return types.CtrlUnpublishResp()

    def ControllerExpandVolume(self, volume_id, capacity_range):
        requested_capacity = capacity_range.required_bytes

        if CONF.mock_vast:
            volume = self._to_mock_volume(volume_id)
            if volume:
                existing_capacity = volume.capacity_bytes
        else:
            quota = self.get_quota(volume_id)
            if quota:
                existing_capacity = quota.hard_limit

        if requested_capacity <= existing_capacity:
            capacity_bytes = existing_capacity
        elif CONF.mock_vast:
            volume.capacity_bytes = capacity_bytes = requested_capacity
        else:
            try:
                self.vms_session.patch(f"quotas/{quota.id}", data=dict(hard_limit=requested_capacity))
            except ApiError as exc:
                raise Abort(
                    OUT_OF_RANGE,
                    f"Failed updating quota {quota.id}: {exc}")
            capacity_bytes = requested_capacity

        return types.CtrlExpandResp(
            capacity_bytes=capacity_bytes,
            node_expansion_required=False,
        )

    def CreateSnapshot(self, source_volume_id, name, parameters=None):
        volume_id = source_volume_id
        path = CONF.root_export[volume_id]

        found = bool(self._to_mock_volume(volume_id) if CONF.mock_vast else self.get_quota(volume_id))
        if not found:
            raise Abort(NOT_FOUND, f"Unknown volume: {volume_id}")

        if CONF.mock_vast:

            try:
                with self.mock_snp_db[name].open("rb") as f:
                    snp = types.Snapshot()
                    snp.ParseFromString(f.read())
                if snp.source_volume_id != volume_id:
                    raise Abort(ALREADY_EXISTS, f"Snapshot name '{name}' is already taken")
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
                with self.mock_snp_db[name].open("wb") as f:
                    f.write(snp.SerializeToString())
        else:
            snapshot_name = parameters['csi.storage.k8s.io/volumesnapshot/name']
            snapshot_namespace = parameters['csi.storage.k8s.io/volumesnapshot/namespace']
            snapshot_name = CONF.snapshot_name_fmt.format(namespace=snapshot_namespace, name=snapshot_name, id=name)
            snapshot_name = snapshot_name.replace(":", "-").replace("/", "-")
            try:
                snap = self.vms_session.post("snapshots", data=dict(name=snapshot_name, path=path))
            except ApiError as exc:
                handled = False
                if exc.response.status_code == 400:
                    try:
                        [(k, [v])] = exc.response.json().items()
                    except (ValueError, JSONDecodeError):
                        pass
                    else:
                        if (k, v) == ('name', 'This field must be unique.'):
                            [snap] = self.vms_session.snapshots(name=snapshot_name)
                            if snap.path != path:
                                raise Abort(ALREADY_EXISTS, f"Snapshot name '{name}' is already taken") from None
                            else:
                                handled = True
                if not handled:
                    raise Abort(INVALID_ARGUMENT, str(exc))

            creation_time = types.Timestamp()
            creation_time.FromDatetime(datetime.fromisoformat(snap.created.rstrip("Z")))

            snp = types.Snapshot(
                size_bytes=0,  # indicates 'unspecified'
                snapshot_id=str(snap.id),
                source_volume_id=volume_id,
                creation_time=creation_time,
                ready_to_use=True,
            )

        return types.CreateSnapResp(snapshot=snp)

    def DeleteSnapshot(self, snapshot_id):
        if CONF.mock_vast:
            self.mock_snp_db[snapshot_id].delete()
        else:
            self.vms_session.delete(f"snapshots/{snapshot_id}")

        return types.DeleteSnapResp()

    @classmethod
    def _to_volume_id(cls, path):
        vol_id = str(local.path(path).relative_to(CONF.root_export))
        return None if vol_id.startswith("..") else vol_id

    def ListSnapshots(self, max_entries=None, starting_token=None, source_volume_id=None, snapshot_id=None):
        if CONF.mock_vast:
            starting_inode = int(starting_token) if starting_token else 0
            snaps = (d for d in os.scandir(self.mock_snp_db) if d.is_file())
            snaps = sorted(snaps, key=lambda d: d.inode())
            logger.info(f"Got {len(snaps)} snapshots in {self.mock_snp_db}")
            start_idx = 0

            logger.info(f"Skipping to {starting_inode}")
            for start_idx, d in enumerate(snaps):
                if d.inode() > starting_inode:
                    break
            del snaps[:start_idx]

            def to_snapshot(dentry):
                with local.path(dentry.path).open("rb") as f:
                    snap = types.Snapshot()
                    snap.ParseFromString(f.read())
                if source_volume_id and snap.source_volume_id != source_volume_id:
                    return
                if snapshot_id and snap.snapshot_id != snapshot_id:
                    return
                return snap, dentry.inode()

            snaps = list(filter(None, map(to_snapshot, snaps)))
            remain = 0
            if max_entries:
                remain = at_least(0, len(snaps) - max_entries)
                snaps = snaps[:max_entries]

            next_token = str(snaps[-1][1]) if remain else None
            return types.ListSnapResp(next_token=next_token, entries=[types.SnapEntry(snapshot=snap) for snap, _ in snaps])
        else:
            if starting_token:
                ret = self.vms_session.snapshots(
                    id=snapshot_id, path=CONF.root_export[source_volume_id], page_size=max_entries)
            else:
                ret = self.vms_session.get(starting_token)
            return types.ListSnapResp(next_token=ret.next_token, entries=[types.SnapEntry(snapshot=types.Snapshot(
                size_bytes=0,  # indicates 'unspecified'
                snapshot_id=snap.id,
                source_volume_id=self._to_volume_id(snap.path) or 'n/a',
                creation_time=snap.created,
                ready_to_use=True,
            )) for snap in ret.results])


################################################################
#
# Node
#
################################################################


class Node(NodeServicer, Instrumented):

    CAPABILITIES = [
        # types.NodeCapabilityType.STAGE_UNSTAGE_VOLUME,
        # types.NodeCapabilityType.GET_VOLUME_STATS,
    ]

    def NodeGetCapabilities(self):
        return types.NodeCapabilityResp(capabilities=[
            types.NodeCapability(rpc=types.NodeCapability.RPC(type=rpc))
            for rpc in self.CAPABILITIES])

    def NodePublishVolume(self, volume_id, target_path, volume_capability=None, publish_context=None, readonly=False, volume_context=None):
        if is_ephemeral := volume_context and volume_context.get('csi.storage.k8s.io/ephemeral') == "true":
            from .quantity import parse_quantity
            controller = Controller()
            required_bytes = int(parse_quantity(volume_context["size"]))
            pod_uid = volume_context['csi.storage.k8s.io/pod.uid']
            pod_name = volume_context['csi.storage.k8s.io/pod.name']
            pod_namespace = volume_context['csi.storage.k8s.io/pod.namespace']
            eph_volume_name = CONF.eph_volume_name_fmt.format(namespace=pod_namespace, name=pod_name, id=pod_uid)
            controller.CreateVolume.__wrapped__(
                controller, name=volume_id, volume_capabilities=[],
                ephemeral_volume_name=eph_volume_name,
                capacity_range=Bunch(required_bytes=required_bytes))
            resp = controller.ControllerPublishVolume.__wrapped__(
                controller, node_id=CONF.node_id, volume_id=volume_id,
                volume_capability=volume_capability)
            publish_context = resp.publish_context
        elif not volume_capability:
            raise Abort(INVALID_ARGUMENT, "missing 'volume_capability'")

        nfs_server_ip = publish_context["nfs_server_ip"]
        export_path = publish_context["export_path"]
        source_path = local.path(export_path)[volume_id]
        mount_spec = f"{nfs_server_ip}:{source_path}"

        _validate_capabilities([volume_capability])
        target_path = local.path(target_path)
        if target_path.is_dir():
            found_mount = next((m for m in psutil.disk_partitions(all=True) if m.mountpoint == target_path), None)
            if found_mount:
                opts = set(found_mount.opts.split(","))
                is_readonly = "ro" in opts
                if found_mount.device != mount_spec:
                    raise Abort(
                        ALREADY_EXISTS,
                        f"Volume already mounted from {found_mount.device} instead of {mount_spec}")
                elif is_readonly != readonly:
                    raise Abort(
                        ALREADY_EXISTS,
                        f"Volume already mounted as {'readonly' if is_readonly else 'readwrite'}")
                else:
                    logger.info(f"{volume_id} is already mounted: {found_mount}")

        target_path.mkdir()
        with target_path['.vast-csi-meta'].open("w") as f:
            json.dump(dict(volume_id=volume_id, is_ephemeral=is_ephemeral), f)
        logger.info(f"created: {target_path}")

        flags = ["ro"] if readonly else []
        if volume_capability.mount.mount_flags:
            flags += volume_capability.mount.mount_flags
        else:
            flags += CONF.mount_options
        mount(mount_spec, target_path, flags=",".join(flags))
        logger.info(f"mounted: {target_path} flags: {flags}")
        return types.NodePublishResp()

    def NodeUnpublishVolume(self, target_path):
        target_path = local.path(target_path)
        if not target_path.exists():
            logger.info(f"{target_path} does not exist - no need to remove")
        else:
            try:
                local.cmd.umount(target_path)
            except ProcessExecutionError as exc:
                if any(p in exc.stderr for p in ("Invalid argument", "not mounted")):
                    logger.info(f"seems it's already unmounted ({exc.stderr})")
                else:
                    raise
            logger.info(f"Deleting {target_path}")
            if target_path['.vast-csi-meta'].exists():
                with target_path['.vast-csi-meta'].open("r") as f:
                    meta = json.load(f)
                if meta.get("is_ephemeral"):
                    controller = Controller()
                    controller.DeleteVolume.__wrapped__(controller, meta['volume_id'])

            local.path(target_path).delete()
            logger.info(f"{target_path} removed successfully")
        return types.NodeUnpublishResp()

    def NodeGetInfo(self):
        return types.NodeInfoResp(node_id=CONF.node_id)


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

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    identity = Identity()
    csi_pb2_grpc.add_IdentityServicer_to_server(identity, server)

    identity.capabilities.append(types.ExpansionType.ONLINE)

    if CONF.mode in {CONTROLLER, CONTROLLER_AND_NODE}:
        identity.controller = Controller()
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_pb2_grpc.add_ControllerServicer_to_server(identity.controller, server)
        identity.controller.mock_vol_db.mkdir()
        identity.controller.mock_snp_db.mkdir()

    if CONF.mode in {NODE, CONTROLLER_AND_NODE}:
        identity.node = Node()
        csi_pb2_grpc.add_NodeServicer_to_server(identity.node, server)

    server.add_insecure_port(CONF.endpoint)
    server.start()

    logger.info(f"Server started as '{CONF.mode}', listening on {CONF.endpoint}")
    server.wait_for_termination()
