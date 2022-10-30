import socket
from typing import List, Dict, NamedTuple, Optional, Union, get_origin, get_args, Any

import grpc
from plumbum import local
from plumbum.typed_env import TypedEnv

from easypy.tokens import (
    Token,
    ROUNDROBIN,
    RANDOM,
    CONTROLLER_AND_NODE,
    CONTROLLER,
    NODE,
)
from .exceptions import Abort


LOAD_BALANCING_STRATEGIES = {ROUNDROBIN, RANDOM}


class Config(TypedEnv):
    class Path(TypedEnv.Str):
        convert = staticmethod(local.path)

    plugin_name, plugin_version, git_commit = (
        open("version.info").read().strip().split()
    )
    plugin_name = TypedEnv.Str("X_CSI_PLUGIN_NAME", default=plugin_name)

    controller_root_mount = Path(
        "X_CSI_CTRL_ROOT_MOUNT", default=local.path("/csi-volumes")
    )
    mock_vast = TypedEnv.Bool("X_CSI_MOCK_VAST", default=False)
    nfs_server = TypedEnv.Str("X_CSI_NFS_SERVER", default="127.0.0.1")
    vip_pool_name = TypedEnv.Str("X_CSI_VIP_POOL_NAME", default="k8s")
    nfs_export = Path("X_CSI_NFS_EXPORT", default=local.path("/k8s"))

    log_level = TypedEnv.Str("X_CSI_LOG_LEVEL", default="info")
    csi_sanity_test = TypedEnv.Bool("X_CSI_SANITY_TEST", default=False)
    node_id = TypedEnv.Str("X_CSI_NODE_ID", default=socket.getfqdn())

    vms_host = TypedEnv.Str("X_CSI_VMS_HOST", default="vast")
    vms_user = TypedEnv.Str("X_CSI_VMS_USER", default="admin")
    vms_password = TypedEnv.Str("X_CSI_VMS_PASSWORD", default="admin")
    ssl_verify = TypedEnv.Bool("X_CSI_DISABLE_VMS_SSL_VERIFICATION", default=False)

    _mode = TypedEnv.Str("CSI_MODE", default="controller_and_node")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default="unix:///var/run/csi.sock")

    _mount_options = TypedEnv.Str("X_CSI_MOUNT_OPTIONS", default="")  # For example: "port=2049,nolock,vers=3"

    @property
    def mount_options(self):
        s = self._mount_options.strip()
        return list({p for p in s.split(',') if p})

    unmount_attempts = TypedEnv.Int("X_CSI_UNMOUNT_ATTEMPTS", default=10)

    @property
    def mode(self):
        mode = Token(self._mode.upper())
        assert mode in {CONTROLLER_AND_NODE, CONTROLLER, NODE}, f"invalid mode: {mode}"
        return mode

    @property
    def endpoint(self):
        return self._endpoint.strip("tcp://")


class StorageClassOptions(NamedTuple):
    """StorageClass context taken from parameters that used in 'CreateVolume' actions."""

    root_export: str
    vip_pool_name: str
    mount_options: Optional[str]
    load_balancing: Optional[str]
    volume_name_fmt: Optional[str]
    snapshot_name_fmt: Optional[str]
    eph_volume_name_fmt: Optional[str]

    @classmethod
    def defaults(cls, include_root_export: Optional[bool] = False):
        """
        Default options.
        Used in cases where parameters were not specified in StorageClass
        or in methods that do not have access to StorageClass parameters.
        """
        _defaults = dict(
            vip_pool_name="",
            mount_options="",
            load_balancing="roundrobin",
            eph_volume_name_fmt="csi:{namespace}:{name}:{id}",
            snapshot_name_fmt="csi:{namespace}:{name}:{id}",
            volume_name_fmt="csi:{namespace}:{name}:{id}",
        )
        if include_root_export:
            _defaults["root_export"] = "/exports"
        return _defaults

    @classmethod
    def from_dict(cls, kwargs: Dict[str, Any]) -> "StorageClassOptions":
        """
        Create StorageClassOptions from provided dictionary.
        Missing arguments are populated using default arguments.
        """
        kwargs = {
            k: v
            for k, v in {**cls.defaults(), **(kwargs or {})}.items()
            if k in StorageClassOptions._fields
        }
        storage_options = StorageClassOptions(**kwargs)
        # Validate required params
        storage_options._validate_required_params()
        return storage_options

    @classmethod
    def with_defaults(cls, **kwargs: Optional[Dict[str, Any]]) -> "StorageClassOptions":
        """
        Init empty StorageClassOptions with default values.
        **kwargs: Optional keyword arguments to include in StorageClassOptions instance
        """
        return StorageClassOptions(**{
            **cls.defaults(include_root_export=True),
            **kwargs
        })

    @property
    def normalized_mount_options(self) -> List[str]:
        """Convert mount options to list if mount options were provided as string on StorageClass parameters level."""
        s = self.mount_options.strip()
        mount_options = list({p for p in s.split(",") if p})
        return mount_options

    @property
    def load_balancing_strategy(self):
        """Convert load balancing to 'Token' representation."""
        lb = Token(self.load_balancing.upper())
        if lb not in LOAD_BALANCING_STRATEGIES:
            raise Exception(
                f"invalid load balancing strategy: {lb} (use {'|'.join(LOAD_BALANCING_STRATEGIES)})"
            )
        return lb

    @property
    def root_export_path(self) -> local.path:
        """Convert 'root_export' attribute to local.path"""
        return local.path(self.root_export)

    def dict(self) -> Dict[str, str]:
        """Convert StorageClassOptions to dict."""
        return self._asdict()

    def _validate_required_params(self):
        """
        Validation based on typing annotations. Attribute is considered to be optional in case it has
        typing.Optional type.
        All required attributes must have a value other than None or empty string.
        """
        for field_name, field_type in self.__annotations__.items():
            if get_origin(field_type) is Union and type(None) in get_args(field_type):
                continue

            if not getattr(self, field_name):
                raise Abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    f"Parameter {field_name!r} cannot be empty string or None."
                    f" Please provide a valid value for this parameter "
                    f"in the parameters of StorageClass section",
                )
