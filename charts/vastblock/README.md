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
helm install csi-driver vast/vastblock -f values.yaml -n vast-block --create-namespace --version 2.6.5
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

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
