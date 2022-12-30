import socket

from plumbum import local
from plumbum.typed_env import TypedEnv

from easypy.tokens import (
    Token,
    CONTROLLER_AND_NODE,
    CONTROLLER,
    NODE,
)


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
    deletion_vip_pool = TypedEnv.Str("X_CSI_DELETION_VIP_POOL_NAME", default="k8s")
    sanity_test_nfs_export = Path("X_CSI_NFS_EXPORT", default=local.path("/k8s"))

    log_level = TypedEnv.Str("X_CSI_LOG_LEVEL", default="info")
    csi_sanity_test = TypedEnv.Bool("X_CSI_SANITY_TEST", default=False)
    node_id = TypedEnv.Str("X_CSI_NODE_ID", default=socket.getfqdn())

    vms_host = TypedEnv.Str("X_CSI_VMS_HOST", default="vast")
    vms_user = TypedEnv.Str("X_CSI_VMS_USER", default="admin")
    vms_password = TypedEnv.Str("X_CSI_VMS_PASSWORD", default="admin")
    ssl_verify = TypedEnv.Bool("X_CSI_DISABLE_VMS_SSL_VERIFICATION", default=False)
    load_balancing = TypedEnv.Str("X_CSI_LB_STRATEGY", default="roundrobin")

    _mode = TypedEnv.Str("CSI_MODE", default="controller_and_node")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default="unix:///var/run/csi.sock")
    _mount_options = TypedEnv.Str("X_CSI_MOUNT_OPTIONS", default="")  # For example: "port=2049,nolock,vers=3"
    name_fmt = "csi:{namespace}:{name}:{id}"

    fake_quota_store = local.path("/tmp/volumes")
    fake_snapshot_store = local.path("/tmp/snapshots")

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
