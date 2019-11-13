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
import inspect
from . logging import logger, init_logging

from . utils import patch_traceback_format
from plumbum import local
from plumbum.typed_env import TypedEnv
from uuid import uuid4


import grpc
from easypy.misc import kwargs_resilient, at_least
from easypy.caching import cached_property

from . import csi_pb2_grpc
from .csi_pb2_grpc import ControllerServicer, NodeServicer, IdentityServicer
from . import csi_types as types


class Config(TypedEnv):

    plugin_name, plugin_version, git_commit = open("version.info").read().strip().split()

    controller_root_mount = TypedEnv.Str("X_CSI_CTRL_ROOT_MOUNT", default=f"/mnt/{plugin_name}/nfs-volumes")
    nfs_server_ip = TypedEnv.Str("X_CSI_NFS_SERVER_IP", default="127.0.0.1")
    root_export = TypedEnv.Str("X_CSI_NFS_EXPORT", default="/tmp/csi-volumes")
    log_level = TypedEnv.Str("X_CSI_LOG_LEVEL", default="info")
    node_id = TypedEnv.Str("X_CSI_NODE_ID", default=socket.getfqdn())

    _mode = TypedEnv.Str("CSI_MODE", default="all")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default=f'unix:///var/run/csi.sock')

    @property
    def mode(self):
        mode = self._mode
        assert mode in {"all", "controller", "node"}, f"invalid mode: {mode}"
        return mode

    @property
    def endpoint(self):
        return self._endpoint.strip("tcp://")


CONF = None


FAILED_PRECONDITION = grpc.StatusCode.FAILED_PRECONDITION
INVALID_ARGUMENT = grpc.StatusCode.INVALID_ARGUMENT
ALREADY_EXISTS = grpc.StatusCode.ALREADY_EXISTS
NOT_FOUND = grpc.StatusCode.NOT_FOUND
ABORTED = grpc.StatusCode.ABORTED
UNKNOWN = grpc.StatusCode.UNKNOWN

SUPPORTED_ACCESS = [
    types.AccessModeType.SINGLE_NODE_WRITER,
    # types.AccessModeType.SINGLE_NODE_READER_ONLY,
    # types.AccessModeType.MULTI_NODE_READER_ONLY,
    # types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
    types.AccessModeType.MULTI_NODE_MULTI_WRITER,
]


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
        elif capability.mount.fs_type != "nfs":
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

    def logged(func):

        method = func.__name__

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

            logger.info(f"{peer} >>> {method}:")

            for line in pformat(params).splitlines():
                logger.info(f"    {line}")

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
            logger.info(f"{peer} <<< {method}:")
            for line in pformat(ret).splitlines():
                logger.info(f"    {line}")

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


class Identity(IdentityServicer, Instrumented):

    def __init__(self):
        self.capabilities = []

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
        if True:
            return types.ProbeRespOK
        else:
            raise Abort(FAILED_PRECONDITION, 'something is wrong')


class Controller(ControllerServicer, Instrumented):

    CAPABILITIES = [
        types.CtrlCapabilityType.CREATE_DELETE_VOLUME,
        # types.CtrlCapabilityType.PUBLISH_UNPUBLISH_VOLUME,
        types.CtrlCapabilityType.LIST_VOLUMES,
        # types.CtrlCapabilityType.GET_CAPACITY,
        # types.CtrlCapabilityType.CREATE_DELETE_SNAPSHOT,
        # types.CtrlCapabilityType.LIST_SNAPSHOTS,
        # types.CtrlCapabilityType.CLONE_VOLUME,
        # types.CtrlCapabilityType.PUBLISH_READONLY,
    ]

    @cached_property
    def root_mount(self):
        target_path = local.path(CONF.controller_root_mount)
        if not target_path.exists():
            target_path.mkdir()
            target_path["NOT_MOUNTED"].touch()

        if target_path["NOT_MOUNTED"].exists():
            mount_spec = f"{CONF.nfs_server_ip}:{CONF.root_export}"
            local.cmd.mount(mount_spec, target_path)
            logger.info(f"{target_path} mounted successfully")

        return target_path

    def ControllerGetCapabilities(self):
        return types.CtrlCapabilityResp(capabilities=[
            types.CtrlCapability(rpc=types.CtrlRPC(type=rpc))
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

        if starting_token:
            try:
                starting_inode = int(starting_token)
            except ValueError:
                raise Abort(ABORTED, "Invalid starting_token")
        else:
            starting_inode = 0

        fields = {'entries': []}

        vols = (d for d in os.scandir(self.root_mount) if d.is_dir())
        vols = sorted(vols, key=lambda d: d.inode())
        if not vols:
            logger.info(f"No volumes in {self.root_mount}")
            return types.ListResp(**fields)

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

        fields['entries'] = [types.Entry(
            volume=self._to_volume(vol.name))
            for vol in vols]

        return types.ListResp(**fields)

    def _to_volume(self, vol_id):
        vol_dir = self.root_mount[vol_id]
        if not vol_dir.is_dir():
            return
        with vol_dir['csi.params'].open("rb") as f:
            vol = types.Volume()
            vol.ParseFromString(f.read())
            return vol

    def CreateVolume(self, name, volume_capabilities, capacity_range=None):
        volume_id = name
        _validate_capabilities(volume_capabilities)

        capacity_bytes = 0
        volume_context = dict(limit="0")

        if capacity_range:
            capacity_bytes = capacity_range.required_bytes
            volume_context.update(limit=str(capacity_range.limit_bytes))

        volume = self._to_volume(volume_id)

        if volume:
            if volume.capacity_bytes != capacity_bytes:
                raise Abort(
                    ALREADY_EXISTS,
                    "Volume already exists with different capacity than requested"
                    f"({volume.capacity_bytes})")

            volume_limit = volume.volume_context.get("limit")
            if volume_limit != volume_context.get("limit"):
                raise Abort(
                    ALREADY_EXISTS,
                    "Volume already exists with different limit than requested"
                    f"({volume_limit})")
        else:
            volume = types.Volume(
                capacity_bytes=capacity_bytes,
                volume_id=volume_id,
                volume_context=volume_context)

            vol_dir = self.root_mount[volume_id]
            vol_dir.mkdir()

            with vol_dir['csi.params'].open("wb") as f:
                f.write(volume.SerializeToString())

        return types.CreateResp(volume=volume)

    def DeleteVolume(self, volume_id):
        vol_dir = self.root_mount[volume_id]
        vol_dir.delete()
        logger.info(f"Removed volume: {vol_dir}")
        return types.DeleteResp()

    def GetCapacity(self):
        cap = os.statvfs(self.root_mount).f_favail
        return types.CapacityResp(available_capacity=cap)


class Node(NodeServicer, Instrumented):

    CAPABILITIES = [
        # types.NodeCapabilityType.STAGE_UNSTAGE_VOLUME,
        # types.NodeCapabilityType.GET_VOLUME_STATS,
    ]

    def NodeGetCapabilities(self):
        return types.NodeCapabilityResp(capabilities=[
            types.NodeCapability(rpc=types.NodeRPC(type=rpc))
            for rpc in self.CAPABILITIES])

    def NodePublishVolume(self, volume_id, target_path, volume_capability, readonly=False):
        _validate_capabilities([volume_capability])
        local.path(target_path).mkdir()
        source_path = local.path(CONF.root_export)[volume_id]
        mount_spec = f"{CONF.nfs_server_ip}:{source_path}"

        flags = []
        if readonly:
            flags.appedn("-o=ro")

        local.cmd.mount(mount_spec, target_path, *flags)
        logger.info(f"{target_path} mounted successfully")
        return types.NodePublishResp()

    def NodeUnpublishVolume(self, target_path):
        target_path = local.path(target_path)
        if not target_path.exists():
            logger.info(f"{target_path} does not exist - no need to remove")
        else:
            local.cmd.umount(target_path)
            logger.info(f"Deleting {target_path}")
            local.path(target_path).delete()
            logger.info(f"{target_path} removed successfully")
        return types.NodeUnpublishResp()

    def NodeGetInfo(self):
        return types.NodeInfoResp(node_id=CONF.node_id)


def serve():
    logger.info("%s: %s (%s)", CONF.plugin_name, CONF.plugin_version, CONF.git_commit)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    identity = Identity()
    csi_pb2_grpc.add_IdentityServicer_to_server(identity, server)

    if CONF.mode in {'controller', 'all'}:
        identity.capabilities.append(types.ServiceType.CONTROLLER_SERVICE)
        csi_pb2_grpc.add_ControllerServicer_to_server(Controller(), server)

    if CONF.mode in {'node', 'all'}:
        csi_pb2_grpc.add_NodeServicer_to_server(Node(), server)

    server.add_insecure_port(CONF.endpoint)
    server.start()

    logger.info(f"Server Started, listening on {CONF.endpoint}")
    server.wait_for_termination()


if __name__ == '__main__':
    patch_traceback_format()
    CONF = Config()
    init_logging(level=CONF.log_level)
    serve()
