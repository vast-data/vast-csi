"""Kubernetes node helpers for CSI e2e (host tlshd, VAST NFS, CSI node DaemonSet)."""
from __future__ import annotations

from typing import List, Optional

from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.timing import wait
from easypy.units import MINUTE

from lib.builders.base import resource_name
from lib.constants import CSI_NAMESPACE
from lib.k8s._base import KubernetesResource
from lib.logging import logger

CSI_NODE_APP_LABEL = "app=csi-vast-node"
CSI_PLUGIN_CONTAINER = "csi-vast-plugin"
TLSHD_CONF_HOST_PATH = "/etc/tlshd.conf"
TLSHD_TRUSTSTORE_HOST_PATH = "/etc/vast-csi-e2e-nfs-server-ca.pem"

# VAST NFS client: https://vastnfs.vastdata.com/docs/4.5/index.html
VASTNFS_VERSION_DEFAULT = "4.5.8"
KTLS_UTILS_DEB_URL = (
    "https://archive.ubuntu.com/ubuntu/pool/universe/k/ktls-utils/"
    "ktls-utils_0.11-1_amd64.deb"
)


class Node(KubernetesResource):
    resource_type = "node"

    def names(self) -> List[str]:
        """Return Kubernetes node names (hostname)."""
        nodes = Bunch.from_json(self.k8s.kubectl("get", "nodes", "-o", "json"))
        return [n.metadata.name for n in nodes["items"]]

    def ensure_tlshd_conf(
        self,
        node_names: Optional[List[str]] = None,
        *,
        namespace: str = CSI_NAMESPACE,
    ) -> None:
        """Create host ``/etc/tlshd.conf`` before helm if missing.

        The vastcsi chart mounts this path as ``hostPath`` type ``File``. Kubelet
        fails CSI node pods when the file does not exist yet.
        """
        targets = node_names if node_names is not None else self.names()
        if not targets:
            raise RuntimeError("No Kubernetes nodes found to seed tlshd.conf")
        for node in targets:
            self._run_host_script(
                node,
                namespace=namespace,
                name_prefix="tlshd-seed",
                script=self._tlshd_seed_script(),
                log_msg=f"Seeding {TLSHD_CONF_HOST_PATH} on node {node!r}",
            )

    def ensure_nfs_mtls_host_stack(
        self,
        node_names: Optional[List[str]] = None,
        *,
        namespace: str = CSI_NAMESPACE,
        vastnfs_version: str = VASTNFS_VERSION_DEFAULT,
    ) -> None:
        """Install host packages needed for ``xprtsec=mtls`` mounts.

        * ``nfs-common`` (userspace understands ``xprtsec``)
        * ``ktls-utils`` >= 0.11 (``tlshd``)
        * VAST NFS kernel modules (``xprtsec`` / TLS stack features)

        Does not change Helm charts. Safe to re-run (idempotent checks).
        """
        targets = node_names if node_names is not None else self.names()
        if not targets:
            raise RuntimeError("No Kubernetes nodes found for NFS mTLS host prep")
        for node in targets:
            self._run_host_script(
                node,
                namespace=namespace,
                name_prefix="vastnfs-prep",
                script=self._nfs_mtls_host_prep_script(vastnfs_version),
                log_msg=f"Preparing NFS mTLS host stack on node {node!r}",
                timeout=20 * MINUTE,
            )

    def _point_csi_mount_nfs_at_host(self, namespace: str = CSI_NAMESPACE) -> None:
        """Make CSI node pods use the host ``mount.nfs`` (supports ``xprtsec``).

        The CSI plugin image currently ships nfs-utils 2.5.x which rejects
        ``xprtsec`` / ``cert_serial``. Host Ubuntu 24.04 nfs-common 2.6.x (and
        VAST NFS) understand those options. Without rebuilding the CSI image,
        wrap the in-container helpers via ``nsenter`` into the host mount NS.
        """
        wait(
            2 * MINUTE,
            lambda: self._csi_node_pods_ready(namespace),
            message="csi-vast-node pods not Ready before mount.nfs wrap",
        )
        pods = self.k8s.pods.get(labels={"app": "csi-vast-node"}, namespace=namespace) or []
        if not pods:
            raise RuntimeError("No csi-vast-node pods to patch mount.nfs helpers")
        script = self._csi_host_mount_nfs_wrapper_script()
        for pod in pods:
            name = pod.metadata.name
            logger.info(f"Pointing mount.nfs at host inside {name!r}/{CSI_PLUGIN_CONTAINER}")
            out = self.k8s.kubectl(
                "exec", "-n", namespace, name, "-c", CSI_PLUGIN_CONTAINER, "--",
                "bash", "-lc", script,
            )
            if out is None:
                raise RuntimeError(f"kubectl exec failed patching mount.nfs in {name!r}")
            logger.info(f"{name}: {out.strip()}")

    def configure_tlshd_truststore(
        self,
        ca_pem: str,
        node_names: Optional[List[str]] = None,
        *,
        namespace: str = CSI_NAMESPACE,
        truststore_path: str = TLSHD_TRUSTSTORE_HOST_PATH,
    ) -> None:
        """Write *ca_pem* into host ``tlshd.conf`` on each node via a privileged pod."""
        targets = node_names if node_names is not None else self.names()
        if not targets:
            raise RuntimeError("No Kubernetes nodes found to configure tlshd truststore")
        for node in targets:
            self._run_host_script(
                node,
                namespace=namespace,
                name_prefix="tlshd-cfg",
                script=self._tlshd_setup_script(ca_pem, truststore_path),
                log_msg=f"Configuring tlshd truststore on node {node!r}",
            )

    def restart_csi_node_pods(self, namespace: str = CSI_NAMESPACE) -> None:
        """Restart CSI node pods so ``csi-nfs-services`` re-reads host tlshd.conf."""
        logger.info("Restarting csi-vast-node pods to pick up tlshd.conf")
        self.k8s.kubectl(
            "delete", "pod", "-n", namespace,
            "-l", CSI_NODE_APP_LABEL,
            "--wait=false",
        )
        wait(
            5 * MINUTE,
            lambda: self._csi_node_pods_ready(namespace),
            message="csi-vast-node pods not Ready after restart",
        )
        # Wrapper lives in the container rootfs and is lost on restart.
        self._point_csi_mount_nfs_at_host(namespace=namespace)

    def _csi_node_pods_ready(self, namespace: str) -> bool:
        pods = self.k8s.pods.get(labels={"app": "csi-vast-node"}, namespace=namespace) or []
        if not pods:
            return False
        for pod in pods:
            if getattr(pod.metadata, "deletionTimestamp", None):
                return False
            status = getattr(pod, "status", None)
            if getattr(status, "phase", None) != "Running":
                return False
            containers = getattr(status, "containerStatuses", None) or []
            by_name = {c.name: c for c in containers}
            plugin = by_name.get(CSI_PLUGIN_CONTAINER)
            if plugin is None or not getattr(plugin, "ready", False):
                return False
        return True

    def _run_host_script(
        self,
        node: str,
        *,
        namespace: str,
        name_prefix: str,
        script: str,
        log_msg: str,
        timeout=2 * MINUTE,
    ) -> None:
        pod_name = resource_name("pod", f"{name_prefix}-{random_nice_name(max_length=16)}")
        body = Bunch.from_dict(
            {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {"name": pod_name, "namespace": namespace},
                "spec": {
                    "restartPolicy": "Never",
                    "hostPID": True,
                    "hostNetwork": True,
                    "nodeSelector": {"kubernetes.io/hostname": node},
                    "tolerations": [{"operator": "Exists"}],
                    "containers": [
                        {
                            "name": "setup",
                            "image": "docker.io/library/busybox",
                            "imagePullPolicy": "IfNotPresent",
                            "command": ["sh", "-c", script],
                            "securityContext": {"privileged": True},
                            "volumeMounts": [{"name": "host", "mountPath": "/host"}],
                        }
                    ],
                    "volumes": [
                        {"name": "host", "hostPath": {"path": "/", "type": "Directory"}}
                    ],
                },
            }
        )
        logger.info(f"{log_msg} via {pod_name}")
        self.k8s.apply([body])
        self.k8s.creation_recorder.record("pod", pod_name, namespace)
        try:
            wait(
                timeout,
                lambda: (
                    (p := self.k8s.pods.get(name=pod_name, namespace=namespace)) is not None
                    and getattr(getattr(p, "status", None), "phase", None) == "Succeeded"
                ),
                message=f"host setup pod {pod_name!r} on {node!r} did not succeed",
            )
        except Exception:
            logger.error(self.k8s.kubectl("logs", pod_name, "-n", namespace) or "")
            logger.error(self.k8s.kubectl("describe", "pod", pod_name, "-n", namespace) or "")
            raise

    @staticmethod
    def _tlshd_seed_script() -> str:
        return f"""
set -eu
CONF=/host{TLSHD_CONF_HOST_PATH}
if [ -f "$CONF" ]; then
  echo "already exists: $CONF"
  exit 0
fi
# Minimal file so chart hostPath type=File can mount; truststore filled later.
printf '%s\\n' '[authenticate.client]' '# seeded by vast-csi e2e before helm' > "$CONF"
chmod 644 "$CONF"
echo "created $CONF"
""".strip()

    @staticmethod
    def _nfs_mtls_host_prep_script(vastnfs_version: str) -> str:
        # nsenter into pid 1 so apt/systemctl see the real node (not the busybox root).
        # Requires hostPID=True on the setup pod.
        return f"""
set -eu
nsenter -t 1 -m -u -i -n -- /bin/bash -s <<'HOST'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# The node plugin refuses xprtsec mounts until the ".nfs" keyring exists, and
# only the NFS client modules register it — installing VAST NFS is not enough.
load_nfs_modules() {{
  modprobe sunrpc 2>/dev/null || true
  modprobe nfsv4 2>/dev/null || modprobe nfs 2>/dev/null || true
  if ! grep -q '[[:space:]]\\.nfs:' /proc/keys; then
    echo "ERROR: no .nfs keyring after loading NFS modules; xprtsec mounts will fail" >&2
    exit 1
  fi
  echo ".nfs keyring present"
}}

echo "==> nfs-common + build deps"
apt-get update -qq
apt-get install -y -qq nfs-common curl ca-certificates \
  gcc make dpkg-dev debhelper autotools-dev "linux-headers-$(uname -r)" \
  dkms 2>/dev/null || apt-get install -y -qq nfs-common curl ca-certificates \
  gcc make dpkg-dev debhelper autotools-dev "linux-headers-$(uname -r)"

echo "==> ktls-utils (>= 0.11 preferred)"
if ! dpkg -l ktls-utils 2>/dev/null | grep -q '^ii'; then
  apt-get install -y -qq ktls-utils || true
fi
ver="$(dpkg-query -W -f='${{Version}}' ktls-utils 2>/dev/null || true)"
need_ktls=1
if [ -n "$ver" ]; then
  case "$ver" in
    0.9*|0.10*) need_ktls=1 ;;
    *) need_ktls=0 ;;
  esac
fi
if [ "$need_ktls" = 1 ]; then
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/ktls-utils.deb" "{KTLS_UTILS_DEB_URL}"
  dpkg -i "$tmp/ktls-utils.deb" || apt-get install -f -y -qq
  rm -rf "$tmp"
fi
systemctl enable --now tlshd.service || systemctl restart tlshd.service || true

if [ ! -f {TLSHD_CONF_HOST_PATH} ]; then
  printf '%s\\n' '[authenticate.client]' '# seeded by vast-csi e2e' > {TLSHD_CONF_HOST_PATH}
fi

echo "==> VAST NFS client modules ({vastnfs_version})"
# Already installed/loaded?
if [ -d "/lib/modules/$(uname -r)/updates/bundle" ] || dpkg -l 'vastnfs*' 2>/dev/null | grep -q '^ii'; then
  echo "VAST NFS package or updates/bundle already present"
  if command -v vastnfs-ctl >/dev/null 2>&1; then
    vastnfs-ctl reload || true
  fi
  load_nfs_modules
  exit 0
fi

work="$(mktemp -d)"
cd "$work"
set +e
curl -sSf https://vastnfs.vastdata.com/download.sh | bash -s -- --version {vastnfs_version}
rc=$?
if [ $rc -ne 0 ]; then
  curl -sSf https://vastnfs.vastdata.com/download.sh | bash -s -- --version {vastnfs_version} --source
  rc=$?
fi
set -e
if [ $rc -ne 0 ]; then
  echo "ERROR: failed to download VAST NFS {vastnfs_version}" >&2
  echo "See https://vastnfs.vastdata.com/docs/4.5/install/ubuntu.html" >&2
  exit 1
fi

deb="$(ls -1 ./*.deb 2>/dev/null | head -1 || true)"
if [ -z "$deb" ]; then
  srcdir="$(find . -maxdepth 2 -type d -name 'vastnfs-*' | head -1 || true)"
  if [ -z "$srcdir" ]; then
    tar_file="$(ls -1 vastnfs*.tar.* 2>/dev/null | head -1 || true)"
    if [ -n "$tar_file" ]; then
      tar xf "$tar_file"
      srcdir="$(find . -maxdepth 2 -type d -name 'vastnfs-*' | head -1 || true)"
    fi
  fi
  if [ -z "$srcdir" ] || [ ! -x "$srcdir/build.sh" ]; then
    echo "ERROR: no VAST NFS package or source tree to build" >&2
    ls -la >&2 || true
    exit 1
  fi
  (cd "$srcdir" && ./build.sh bin --no-ofed)
  deb="$(ls -1 "$srcdir"/dist/vastnfs*.deb 2>/dev/null | grep -v debug | head -1 || true)"
fi
if [ -z "$deb" ]; then
  echo "ERROR: VAST NFS .deb not produced" >&2
  exit 1
fi
apt-get install -y -qq "$deb" || dpkg -i "$deb"
depmod -a
update-initramfs -u -k "$(uname -r)" || true
if command -v vastnfs-ctl >/dev/null 2>&1; then
  vastnfs-ctl reload || true
fi
load_nfs_modules
echo "VAST NFS install done (reboot recommended for full module swap)"
HOST
""".strip()

    @staticmethod
    def _csi_host_mount_nfs_wrapper_script() -> str:
        return r"""
set -euo pipefail
# Replace container mount.nfs* (old nfs-utils) with nsenter wrappers to the host.
# Also strip mountproto=* for NFSv4: CSI historically always added mountproto=tcp for
# xprtsec, but mount.nfs rejects that on NFSv4 (EPROTONOSUPPORT).
rm -f /usr/sbin/mount.nfs /usr/sbin/mount.nfs4 /usr/sbin/umount.nfs /usr/sbin/umount.nfs4
cat > /usr/sbin/mount.nfs << 'EOF'
#!/bin/bash
name=$(basename "$0")
args=()
i=0
argv=("$@")
while [[ $i -lt $# ]]; do
  a="${argv[$i]}"
  if [[ "$a" == "-o" || "$a" == -o* ]]; then
    if [[ "$a" == "-o" ]]; then
      i=$((i+1))
      opts="${argv[$i]}"
    else
      opts="${a#-o}"
    fi
    if [[ "$opts" == *vers=4* || "$opts" == *nfsvers=4* ]]; then
      # drop mountproto=* (v3-only)
      opts=$(echo "$opts" | tr ',' '\n' | grep -v '^mountproto=' | paste -sd, -)
    fi
    args+=("-o" "$opts")
  else
    args+=("$a")
  fi
  i=$((i+1))
done
exec nsenter -t 1 -m -u -i -n -- /usr/sbin/"$name" "${args[@]}"
EOF
chmod 755 /usr/sbin/mount.nfs
ln -s mount.nfs /usr/sbin/mount.nfs4
ln -s mount.nfs /usr/sbin/umount.nfs
ln -s mount.nfs /usr/sbin/umount.nfs4
/usr/sbin/mount.nfs --version
""".strip()

    @staticmethod
    def _tlshd_setup_script(ca_pem: str, truststore_path: str) -> str:
        return f"""
set -eu
cat > /host{truststore_path} <<'EOF'
{ca_pem.rstrip()}
EOF
CONF=/host{TLSHD_CONF_HOST_PATH}
if [ ! -f "$CONF" ]; then
  printf '%s\\n' '[authenticate.client]' 'x509.truststore={truststore_path}' > "$CONF"
elif ! grep -q '{truststore_path}' "$CONF"; then
  if grep -q '\\[authenticate.client\\]' "$CONF"; then
    sed -i '/\\[authenticate.client\\]/a x509.truststore={truststore_path}' "$CONF"
  else
    printf '\\n%s\\n%s\\n' '[authenticate.client]' 'x509.truststore={truststore_path}' >> "$CONF"
  fi
fi
chroot /host systemctl restart tlshd 2>/dev/null || chroot /host /bin/systemctl restart tlshd 2>/dev/null || true
chroot /host systemctl start tlshd 2>/dev/null || chroot /host /bin/systemctl start tlshd 2>/dev/null || true
echo OK
""".strip()
