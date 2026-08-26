# Install CSI driver with Helm 3

## Prerequisites
 - [install Helm](https://helm.sh/docs/intro/quickstart/#install-helm)


### install production version of the driver:
```console
helm repo add vast https://vast-data.github.io/vast-csi
helm install csi-driver vast/vastblock -f values.yaml -n vast-block --create-namespace
```

### install beta version of the driver:
```console
helm repo add vast https://raw.githubusercontent.com/vast-data/vast-csi/gh-pages-beta
helm install csi-driver vast/vastblock -f values.yaml -n vast-block --create-namespace
```

> **NOTE:** Optionally modify values.yaml or set overrides via Helm command line 


### install a specific version
```console
helm install csi-driver vast/vastblock -f values.yaml -n vast-block --create-namespace --version 2.6.7
```

### Upgrade driver
```console
helm upgrade csi-driver vast/vastblock -f values.yaml -n vast-block
```

### Upgrade helm repository
```console
helm repo update vast
```

### Uninstall driver
```console
helm uninstall csi-driver  -n vast-block
```

### search for all available chart versions
```console
helm search repo -l vast
```

### Node scheduling (block node DaemonSet)

By default, the block node DaemonSet schedules on all nodes (`node.nodeAffinity: {}`). Control-plane nodes often lack the `nvme-tcp` kernel module required for block volumes; if the block node runs there, it will not crash but will log an error and block volumes will not work on that node until `nvme-tcp` is available. To restrict the block node to worker nodes only, set `node.nodeAffinity` to exclude `node-role.kubernetes.io/control-plane` (see the chart values for an example).

### Block tools and node OS

The block driver requires **host `nvme-cli`** on every worker node. At startup the node plugin searches configured directories under the mounted host root (`/host`) and runs host utilities via `chroot` to the resolved absolute path (no host `/usr/bin/env` required). Override search directories with `node.hostBinarySearchDirs` (comma-separated paths, appended to driver defaults). Each tool (`nvme`, `cryptsetup`, `e2fsck`, `modprobe`, etc.) is resolved once per path list and cached.

**LUKS** volumes require **host `cryptsetup`** on worker nodes that use encrypted StorageClasses. Talos includes `cryptsetup` in the base image (`/usr/sbin/cryptsetup`). GKE COS may need an extra search directory (for example `/home/kubernetes/containerized_mounter/rootfs/usr/sbin`).

The node kernel must have `nvme-tcp` available (built-in or preloaded). The driver checks sysfs first; if the module is not loaded it attempts `modprobe nvme-tcp` on the host (best-effort — on Talos and other minimal OS nodes `modprobe` may be unavailable, so the module must already be present).

The block node DaemonSet uses `hostNetwork`, privileged mode, and mounts `/dev`, `/sys`, and the host root at `/host` so NVMe and LUKS operations target the node's block devices and `/dev/mapper` mappings.

On startup, node logs include resolved host binary paths (for example `host nvme: using /usr/bin/nvme`).

**Talos Linux:** install the **nvme-cli** system extension on workers. Workers need `nvme-tcp` (built-in or extension); schedule the block node DaemonSet on workers, not control-plane. For **LUKS** StorageClasses, Talos may not provide enough `/dev/loopN` nodes for kubelet — patch worker machine config with `kernel.modules.loop` parameter `max_loop` (sized to concurrent block volumes per node) and reboot. Workload namespaces may need `pod-security.kubernetes.io/enforce=privileged` when the cluster enforces restricted Pod Security.

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
