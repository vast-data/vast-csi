import socket

from plumbum import local
from plumbum.typed_env import TypedEnv

from easypy.tokens import (
    Token,
    CONTROLLER_AND_NODE,
    CONTROLLER,
    NODE,
)
from .exceptions import LookupFieldError

from easypy.caching import cached_property
from easypy.timing import Timer
from easypy.units import HOUR, MINUTE
from easypy.bunch import Bunch


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

    ssl_verify = TypedEnv.Bool("X_CSI_ENABLE_VMS_SSL_VERIFICATION", default=False)
    truncate_volume_name = TypedEnv.Int("X_CSI_TRUNCATE_VOLUME_NAME", default=None)
    worker_threads = TypedEnv.Int("X_CSI_WORKER_THREADS", default=10)

    metrics_port = TypedEnv.Int("X_CSI_METRICS_PORT", default=9090)
    metrics_enabled = TypedEnv.Bool("X_CSI_METRICS_ENABLED", default=False)
    
    dont_use_trash_api = TypedEnv.Bool("X_CSI_DONT_USE_TRASH_API", default=False)
    use_local_ip_for_mount = TypedEnv.Str("X_CSI_USE_LOCALIP_FOR_MOUNT", default="")
    attach_required = TypedEnv.Bool("X_CSI_ATTACH_REQUIRED", default=True)
    block_hosts_auto_prune = TypedEnv.Bool("X_CSI_BLOCK_HOSTS_AUTO_PRUNE", default=False)
    force_lazy_umount_on_timeout = TypedEnv.Bool("X_CSI_FORCE_LAZY_UMOUNT_ON_TIMEOUT", default=False)
    disable_usage_stats = TypedEnv.Bool("X_CSI_DISABLE_USAGE_STATS", default=False)
    block_hosts_prefix = TypedEnv.Str("X_CSI_BLOCK_HOSTS_PREFIX", default="")

    _mode = TypedEnv.Str("X_CSI_MODE", default="controller_and_node")
    _endpoint = TypedEnv.Str("CSI_ENDPOINT", default="unix:///var/run/csi.sock")
    _mount_options = TypedEnv.Str("X_CSI_MOUNT_OPTIONS", default="")  # For example: "port=2049,nolock,vers=3"
    # Comma-separated NFS client daemons the node plugin waits for before mounting
    # (set when the csi-nfs-services sidecar is enabled). Empty disables the gate.
    _nfs_services_wait = TypedEnv.Str("X_CSI_NFS_SERVICES_WAIT", default="")
    _vms_host = TypedEnv.Str("X_CSI_VMS_HOST", default="")
    name_fmt = "csi:{id}:{namespace}:{name}"
    block_nqn_prefix = "nqn.2014-08.com.vastcsiblock:"
    max_cache_control_seconds = TypedEnv.Int("X_CSI_CACHE_MAX_AGE", default=0)

    fake_quota_store = local.path("/tmp/volumes")
    fake_snapshot_store = local.path("/tmp/snapshots")

    timeout = TypedEnv.Int("X_CSI_VMS_TIMEOUT", default=30)
    mount_umount_timeout = TypedEnv.Int("X_CSI_MOUNT_UMOUNT_TIMEOUT", default=90)
    resolve_mount_symlinks = TypedEnv.Bool("X_CSI_RESOLVE_MOUNT_SYMLINKS", default=False)
    allow_ro_many_block_fs_mode = TypedEnv.Bool("X_CSI_ALLOW_RO_MANY_BLOCK_FS_MODE", default=False)

    @cached_property
    def vms_user(self):
        if self.vms_credentials_store['username'].exists():
            return self.vms_credentials_store['username'].read().strip()

    @cached_property
    def vms_password(self):
        if self.vms_credentials_store['password'].exists():
            return self.vms_credentials_store['password'].read().strip()

    @cached_property
    def vms_token(self):
        if self.vms_credentials_store['token'].exists():
            return self.vms_credentials_store['token'].read().strip()

    @cached_property
    def vms_tenant(self):
        if self.vms_credentials_store['tenant'].exists():
            return self.vms_credentials_store['tenant'].read().strip()

    @cached_property
    def vms_host(self):
        if self.vms_credentials_store['endpoint'].exists():
            return self.vms_credentials_store['endpoint'].read().strip()
        return self._vms_host

    @cached_property
    def host_encryption_passphrase(self):
        if self.vms_credentials_store['passphrase'].exists():
            return self.vms_credentials_store['passphrase'].read().strip()

    @cached_property
    def cluster_credentials(self):
        """Read multi-cluster auth configuration from the secret"""
        import yaml

        if not self.vms_credentials_store['clusters'].exists():
            raise LookupFieldError(
                field="clusters",
                tip="Make sure multiClusterSecretName "
                    "is specified and contains the required 'clusters' yaml specification"
            )
        with self.vms_credentials_store['clusters'].open() as f:
            return Bunch.from_dict(yaml.safe_load(f))

    @property
    def mount_options(self):
        s = self._mount_options.strip()
        return list({p for p in s.split(',') if p})

    @property
    def nfs_services_wait(self):
        return [p.strip() for p in self._nfs_services_wait.split(',') if p.strip()]

    unmount_attempts = TypedEnv.Int("X_CSI_UNMOUNT_ATTEMPTS", default=10)

    @property
    def mode(self):
        mode = Token(self._mode.upper())
        assert mode in {CONTROLLER_AND_NODE, CONTROLLER, NODE}, f"invalid mode: {mode}"
        return mode

    @property
    def endpoint(self):
        return self._endpoint.strip("tcp://")

    @cached_property
    def has_running_controller(self):
        return self.mode in {CONTROLLER_AND_NODE, CONTROLLER}

    @cached_property
    def has_running_node(self):
        return self.mode in {CONTROLLER_AND_NODE, NODE}

    avoid_trash_api = Timer(now=-1, expiration=HOUR)


# Must match server.ExtensionsSocketPath in the Go extensions-controller.
EXTENSIONS_SOCKET = "/var/run/vast-extensions/extensions.sock"
