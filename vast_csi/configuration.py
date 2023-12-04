import socket

from plumbum import local
from plumbum.typed_env import TypedEnv

from easypy.tokens import (
    Token,
    CONTROLLER_AND_NODE,
    CONTROLLER,
    NODE,
)

from easypy.caching import cached_property
from easypy.timing import Timer
from easypy.units import HOUR


class Config(TypedEnv):
    class Path(TypedEnv.Str):
        convert = staticmethod(local.path)

    vms_credentials_store = local.path("/opt/vms-auth")
    plugin_name, plugin_version, git_commit, ci_pipe = (
        open("version.info").read().strip().split()
    )
    plugin_name = TypedEnv.Str("X_CSI_PLUGIN_NAME", default=plugin_name)

    controller_root_mount = Path(
        "X_CSI_CTRL_ROOT_MOUNT", default=local.path("/csi-volumes")
    )
    mock_vast = TypedEnv.Bool("X_CSI_MOCK_VAST", default=False)
    nfs_server = TypedEnv.Str("X_CSI_NFS_SERVER", default="127.0.0.1")
    deletion_vip_pool = TypedEnv.Str("X_CSI_DELETION_VIP_POOL_NAME", default="k8s")
    deletion_view_policy = TypedEnv.Str("X_CSI_DELETION_VIEW_POLICY", default="")
    sanity_test_nfs_export = Path("X_CSI_NFS_EXPORT", default=local.path("/k8s"))

    log_level = TypedEnv.Str("X_CSI_LOG_LEVEL", default="info")
    csi_sanity_test = TypedEnv.Bool("X_CSI_SANITY_TEST", default=False)
    node_id = TypedEnv.Str("X_CSI_NODE_ID", default=socket.getfqdn())

    vms_host = TypedEnv.Str("X_CSI_VMS_HOST", default="vast")
    ssl_verify = TypedEnv.Bool("X_CSI_ENABLE_VMS_SSL_VERIFICATION", default=False)
    load_balancing = TypedEnv.Str("X_CSI_LB_STRATEGY", default="roundrobin")
    truncate_volume_name = TypedEnv.Int("X_CSI_TRUNCATE_VOLUME_NAME", default=None)
    worker_threads = TypedEnv.Int("X_CSI_WORKER_THREADS", default=10)
    dont_use_trash_api = TypedEnv.Bool("X_CSI_DONT_USE_TRASH_API", default=True)

    _mode = TypedEnv.Str("X_CSI_MODE", default="controller_and_node")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default="unix:///var/run/csi.sock")
    _mount_options = TypedEnv.Str("X_CSI_MOUNT_OPTIONS", default="")  # For example: "port=2049,nolock,vers=3"
    name_fmt = "csi:{namespace}:{name}:{id}"

    fake_quota_store = local.path("/tmp/volumes")
    fake_snapshot_store = local.path("/tmp/snapshots")

    @cached_property
    def vms_user(self):
        return self.vms_credentials_store['username'].read().strip()

    @cached_property
    def vms_password(self):
        return self.vms_credentials_store['password'].read().strip()

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

    avoid_trash_api = Timer(now=-1, expiration=HOUR)
