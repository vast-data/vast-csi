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
import json
import random
import threading
from functools import wraps
from pprint import pformat
import inspect
from contextlib import ExitStack

from requests.exceptions import HTTPError
from plumbum.commands.processes import ProcessExecutionError

from easypy.misc import kwargs_resilient
from easypy.exceptions import TException
from easypy.collections import separate
from easypy.bunch import Bunch
from vast_csi.proto import csi_pb2_grpc as csi_grpc
from vast_csi.proto import addons_identity_pb2, addons_identity_pb2_grpc
from vast_csi import csi_types as types
from vast_csi.csi_types import FAILED_PRECONDITION

from vast_csi.logging import logger
from vast_csi.utils import stringify_dict
from vast_csi.csi_types import INVALID_ARGUMENT, UNKNOWN
from vast_csi.builders import  parse_volume_id
from vast_csi.exceptions import Abort, LookupFieldError
from vast_csi.session import instantiate_session_from_secret, VmsSession
from vast_csi.luks_utils import get_luks_manager, LuksManager
from vast_csi.metrics import get_metrics_registry
from vast_csi.mtls_utils import get_mtls_manager
from vast_csi.quantity import parse_quantity
from vast_csi.logging import logger

CONF = None


# Request ID counter for unique request tracking
# Initialized with a random value in the lower half of uint32 range to avoid predictable sequences
_req_id_counter = random.randint(0, 0x7FFFFFFF)  # [0, max/2]
_req_id_lock = threading.Lock()


def _get_next_uid():
    """Generate a unique request ID with zero-padded hex format (e.g., 0x0000abcd)."""
    global _req_id_counter
    with _req_id_lock:
        _req_id_counter = (_req_id_counter + 1) & 0xFFFFFFFF  # Wrap at uint32 max
        return f"0x{_req_id_counter:08x}"


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
        required_params.discard("self")

        func = kwargs_resilient(func)

        @wraps(func)
        def wrapper(self, request, context):
            uid = _get_next_uid()
            peer = context.peer()
            params = {fld.name: value for fld, value in request.ListFields()}
            # secrets are not logged and not the part of function signature.
            secrets = params.pop("secrets", {})
            missing_params = required_params - {"request", "context", "vms_session", "secondary_vms_session", "exit_stack", "luks_manager", "metrics_registry", "mtls_manager"} - set(params)

            # Get cluster_name from volume_id, snapshot_id or source_volume_id in case of id identifier with metadata
            cluster_names = set()
            for fld in ("volume_id", "snapshot_id", "source_volume_id"):
                if fld in params:
                    id_value = params[fld]
                    orig_value, cluster_name = parse_volume_id(id_value)
                    cluster_names.add(cluster_name)
                    params[fld] = orig_value
            cluster_names.add(params.get("parameters", {}).get("cluster_name"))
            cluster_names.discard(None)
            if not cluster_names:
                cluster_name = None
            elif len(cluster_names) == 1:
                secrets["cluster_name"] = cluster_name = cluster_names.pop()
            else:
                raise Exception(f"too many cluster names specified: {', '.join(cluster_names)}")

            log(f"{peer} >>> [{uid}] {method} ({cluster_name or '-'}):")

            if params:
                for line in stringify_dict(params):
                    log(f"({method})    {line}")

            # Handle source session (vms_session)
            if "vms_session" in required_params:
                params["vms_session"] = instantiate_session_from_secret(secrets)
            elif "vms_session" in non_required_params:
                try:
                    params["vms_session"] = instantiate_session_from_secret(secrets)
                except LookupFieldError:
                    params["vms_session"] = None

            # Handle secondary/destination session (secondary_vms_session)
            if "secondary_vms_session" in required_params:
                params["secondary_vms_session"] = instantiate_session_from_secret(secrets, key_prefix=("secondary_",))
            elif "secondary_vms_session" in non_required_params:
                try:
                    params["secondary_vms_session"] = instantiate_session_from_secret(secrets, key_prefix=("secondary_",))
                except LookupFieldError:
                    params["secondary_vms_session"] = None

            if "luks_manager" in required_params:
                # If method signature requires `luks_manager` parameter
                params["luks_manager"] = get_luks_manager(
                    volume_id=params["volume_id"],
                    passphrase=secrets.get("passphrase", None),
                    volume_context=params.get("volume_context", {}),
                    cluster_name=secrets.get("cluster_name", None),
                )

            if "mtls_manager" in required_params:
                # If method signature requires `mtls_manager` parameter
                # Extract mount_flags from volume_capability (xprtsec comes from mount options)
                mount_flags = ""
                volume_capability = params.get("volume_capability")
                if volume_capability and hasattr(volume_capability, "mount"):
                    mount_flags = ",".join(volume_capability.mount.mount_flags or [])
                params["mtls_manager"] = get_mtls_manager(
                    mtls_client_cert=secrets.get("mtls_client_cert", None),
                    mtls_client_privkey=secrets.get("mtls_client_privkey", None),
                    mount_flags=mount_flags,
                    cluster_name=secrets.get("cluster_name", None),
                )

            exit_stack = ExitStack()

            if CONF.metrics_enabled:
                metrics_registry = get_metrics_registry(
                    params, hostname=CONF.node_id, driver_name=CONF.plugin_name
                )

                if "metrics_registry" in required_params or "metrics_registry" in non_required_params:
                    params["metrics_registry"] = metrics_registry

                # Track CSI operation metrics (execution time + status code)
                exit_stack.enter_context(
                    metrics_registry.csi_operation(method)
                )

            if "exit_stack" in required_params:
                params["exit_stack"] = exit_stack

            try:
                if missing_params:
                    msg = f'Missing required fields: {", ".join(sorted(missing_params))}'
                    logger.error(f"{peer} <<< [{uid}] {method}: {msg}")
                    raise Abort(INVALID_ARGUMENT, msg)

                with exit_stack:
                    ret = func(self, request=request, context=context, **params)
            except Abort as exc:
                logger.error(
                    f'{peer} <<< [{uid}] {method} ABORTED with {exc.code} ("{exc.message}")'
                )
                logger.debug("Traceback", exc_info=True)
                context.abort(exc.code, exc.message)
            except HTTPError as exc:
                reason = exc.response.reason
                status_code = exc.response.status_code
                text = exc.response.text.splitlines()[0]
                resource = exc.request.path_url
                logger.exception(f"[{uid}] Exception during {method}\n{exc.response.text}")
                context.abort(
                    UNKNOWN,
                    f"[{method}]. Unable to accomplish request to {resource}. {text}, <{reason}({status_code})>"
                )
            except TException as exc:
                # Any exception inherited from TException
                logger.exception(f"[{uid}] Exception during {method}")
                context.abort(UNKNOWN, f"[{method}]. {exc.render(color=False)}")
            except Exception as exc:
                logger.exception(f"[{uid}] Exception during {method}")
                text = str(exc)
                context.abort(UNKNOWN, f"[{method}]: {text}")
            if ret:
                log(f"{peer} <<< {method}:")
                for line in pformat(ret).splitlines():
                    log(f"    {line}")
            log(f"[{uid}] {peer} --- {method}: Done")
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

class IdentityBase(csi_grpc.IdentityServicer):
    """
    Base class for implementing the Identity service in the CSI driver.
    The Identity service provides information about the plugin, including its
    name, version.
    """

    def __init__(self):
        self.capabilities = []
        self.controller = None
        self.node = None

    def GetPluginInfo(self, request, context):
        """Retrieve the plugin's name and version."""
        return types.InfoResp(
            name=CONF.plugin_name,
            vendor_version=CONF.plugin_version,
        )

    def GetPluginCapabilities(self, request, context):
        """Retrieve the plugin's capabilities."""
        return types.CapabilitiesResp(
            capabilities=[
                types.Capability(service=types.Service(type=cap))
                for cap in self.capabilities
            ]
        )

    def Probe(self, request, context):
        """Check the health and readiness of the plugin."""
        return types.ProbeRespOK



class AddonsIdentity(addons_identity_pb2_grpc.IdentityServicer):
    """
    Shared Identity service for all CSI-Addons.

    This is a singleton-like class with class-level capabilities that are
    shared across all addon registrations. Each addon adds its capabilities
    when it's loaded.

    CONTROLLER_SERVICE capability is added by default.
    """

    # Class-level list to store capability types (not protobuf objects)
    # Format: ("service", CONTROLLER_SERVICE), ("volume_replication", VOLUME_REPLICATION), etc.
    _capability_types = [("service", "CONTROLLER_SERVICE")]
    _registered = False

    @classmethod
    def add_replication_capabilities(cls):
        """Add VOLUME_REPLICATION capability."""
        entry = ("volume_replication", "VOLUME_REPLICATION")
        if entry not in cls._capability_types:
            cls._capability_types.append(entry)
            from vast_csi.logging import logger
            logger.info(f"Added CSI-Addons capability: {entry}")

    @classmethod
    def add_volume_group_capabilities(cls):
        """Add all VolumeGroup capabilities."""
        entries = [
            ("volume_group", "CREATE_GET_DELETE_VOLUME_GROUP"),
            ("volume_group", "MODIFY_VOLUME_GROUP"),
        ]
        for entry in entries:
            if entry not in cls._capability_types:
                cls._capability_types.append(entry)
                logger.info(f"Added CSI-Addons capability: {entry}")

    @classmethod
    def _build_capabilities(cls):
        """Build protobuf capability objects from stored types."""
        Service = addons_identity_pb2.Capability.Service
        VolumeReplication = addons_identity_pb2.Capability.VolumeReplication
        VolumeGroup = addons_identity_pb2.Capability.VolumeGroup

        capabilities = []
        for category, cap_name in cls._capability_types:
            if category == "service":
                cap_enum = getattr(Service, cap_name)
                capabilities.append(
                    addons_identity_pb2.Capability(
                        service=Service(type=cap_enum)
                    )
                )
            elif category == "volume_replication":
                cap_enum = getattr(VolumeReplication, cap_name)
                capabilities.append(
                    addons_identity_pb2.Capability(
                        volume_replication=VolumeReplication(type=cap_enum)
                    )
                )
            elif category == "volume_group":
                cap_enum = getattr(VolumeGroup, cap_name)
                capabilities.append(
                    addons_identity_pb2.Capability(
                        volume_group=VolumeGroup(type=cap_enum)
                    )
                )
        return capabilities

    @classmethod
    def register(cls, server):
        """Register the identity service on the gRPC server (only once)."""
        if not cls._registered:
            addons_identity_pb2_grpc.add_IdentityServicer_to_server(cls(), server)
            cls._registered = True

    def GetIdentity(self, request, context):
        """
        Retrieve the CSI-Addons identity information.
        Returns the plugin name and version.
        """
        return addons_identity_pb2.GetIdentityResponse(
            name=CONF.plugin_name,
            vendor_version=CONF.plugin_version,
        )

    def GetCapabilities(self, request, context):
        """
        Retrieve the CSI-Addons capabilities.
        Returns capabilities like volume replication support.
        """
        # Build capabilities fresh each time to avoid protobuf issues
        capabilities = self.__class__._build_capabilities()
        return addons_identity_pb2.GetCapabilitiesResponse(
            capabilities=capabilities
        )

    def Probe(self, request, context):
        """Check the health and readiness of the CSI-Addons plugin."""
        return addons_identity_pb2.ProbeResponse(ready=types.Bool(value=True))


################################################################
#
# Controller
#
################################################################

class ControllerBase(csi_grpc.ControllerServicer):
    """
    Base class for implementing the Controller service in the CSI driver.
    The Controller service manages volumes, including creation, deletion,
    and attachment/detachment of volumes to nodes.
    """

    CAPABILITIES = NotImplemented

    def ControllerGetCapabilities(self):
        return types.CtrlCapabilityResp(
            capabilities=[
                types.CtrlCapability(rpc=types.CtrlCapability.RPC(type=rpc))
                for rpc in self.CAPABILITIES
            ]
        )

################################################################
#
# Node
#
################################################################

class NodeBase(csi_grpc.NodeServicer):
    """
    Base class for implementing the Node service in the CSI driver.
    The Node service handles operations at the node level, such as staging,
    publishing, and unpublishing volumes.
    """

    CAPABILITIES = NotImplemented

    def NodeGetCapabilities(self):
        """Retrieve the node's capabilities."""
        return types.NodeCapabilityResp(
            capabilities=[
                types.NodeCapability(rpc=types.NodeCapability.RPC(type=rpc))
                for rpc in self.CAPABILITIES
            ]
        )

    def NodeGetInfo(self):
        """Retrieve information about the node."""
        return types.NodeInfoResp(node_id=CONF.node_id)


    def _get_fs_stats(self, path):
        """Return the filesystem stats for a given path."""
        fstats = os.statvfs(path)
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


    def _get_block_stats(self, path):
        """Return the block stats for a given path."""
        from vast_csi.block_utils import get_nvme_device_stats

        try:
            stats = get_nvme_device_stats(path)
        except ProcessExecutionError as exc:
            if "No such file or directory" in str(exc):
                raise Exception(f"Device not found at {path}")
            raise
        else:
            size = stats.total_bytes
            used = stats.used_bytes
            available = stats.available_bytes
            return types.VolumeStatsResp(
                usage=[
                    types.VolumeUsage(
                        unit=types.UsageUnit.BYTES,
                        available=available,
                        total=size,
                        used=used,
                    ),
                ]
            )

    def _get_publish_context_for_ev_volumes(
            self, volume_context, volume_id, volume_capability, vms_session, exit_stack, **create_vol_kwargs
    ):
        """
        This method implements the logic of a mixin that creates the publish context for ephemeral (EV) volumes.
        It handles the necessary volume creation and publishing steps required for ephemeral volumes.
        """
        if "size" in volume_context:
            required_bytes = int(parse_quantity(volume_context["size"]))
            capacity_range = Bunch(required_bytes=required_bytes)
        else:
            capacity_range = None
        resp = self.controller.CreateVolume.__wrapped__(
            self.controller,
            vms_session=vms_session,
            name=volume_id,
            volume_capabilities=[],
            capacity_range=capacity_range,
            parameters=volume_context,
            **create_vol_kwargs
        )
        volume_context.update(dict(resp.volume.volume_context))
        resp = self.controller.ControllerPublishVolume.__wrapped__(
            self.controller,
            vms_session=vms_session,
            node_id=CONF.node_id,
            volume_id=volume_id,
            volume_capability=volume_capability,
            volume_context=volume_context,
            exit_stack=exit_stack,
        )
        return resp.publish_context


    def _get_publish_context_for_non_attach_required(
            self, vms_session, node_id, volume_id, volume_capability, volume_context, exit_stack
    ):
        """
        This method implements the logic of a mixin that creates
        the publish context for volumes that do not require attachment.
        """
        # Condition when attach_required == False on CSIDriver object
        # In this case ControllerPublishVolume step is skipped on Controller. Node takes care of it.
        assert not CONF.attach_required, "missing 'publish_context' when attach_required is enabled"
        logger.info("attach_required is disabled, obtaining publish context")
        resp = self.controller.ControllerPublishVolume.__wrapped__(
            self.controller,
            vms_session=vms_session,
            node_id=node_id,
            volume_id=volume_id,
            volume_capability=volume_capability,
            exit_stack=exit_stack,
            volume_context=volume_context,
        )
        return resp.publish_context


    def _store_meta_file(
            self,
            meta_file,
            volume_id,
            is_ephemeral,
            vms_session,
            luks_manager=None,
            extra_data=None,
    ):
        """
        Stores metadata about a volume in a file, including information about
        whether the volume is ephemeral, host_encryption and, if so, serialized session data.

        Args:
            extra_data: Optional dict of additional data to store (for protocol-specific needs)
        """
        payload = {
        "volume_id": volume_id,
        "is_ephemeral": is_ephemeral,
        }

        if extra_data:
            payload.update(extra_data)

        if is_ephemeral:
            payload["vms_session"] = vms_session.serialize(salt=volume_id)
            if luks_manager:
                payload["luks_manager"] = luks_manager.serialize(salt=volume_id)

        with meta_file.open("w") as f:
            json.dump(payload, f)
        os.chmod(meta_file, 0o600)


    def _read_and_process_meta_file(self, meta_file, volume_id, vms_session):
        """
        Reads and processes a volume's metadata file, cleaning up resources for
        ephemeral volumes and removing the metadata file.
        """
        with meta_file.open("r") as f:
            meta = json.load(f)
        if meta.get("is_ephemeral"):
            if vms_session_data := meta.get("vms_session"):
                vms_session = VmsSession.deserialize(
                    salt=volume_id, encrypted_blob=vms_session_data
                )
            elif not vms_session:
                raise Abort(
                    FAILED_PRECONDITION,
                    "Ephemeral Volume provisioning requires "
                    "configuring a global VMS credentials secret or nodePublishSecretRef secret reference."
                )
            if luks_manager_data := meta.get("luks_manager"):
                luks_manager = LuksManager.deserialize(
                    salt=volume_id, encrypted_blob=luks_manager_data
                )
                luks_manager.luks_close_device()

            self.controller.DeleteVolume.__wrapped__(
                self.controller, vms_session=vms_session, volume_id=meta["volume_id"]
            )

        return meta
