# Install CSI driver with Helm 3 (GKE)

GKE-oriented Helm chart for the VAST NFS CSI driver. Core controller, node,
CSIDriver, RBAC, StorageClass, SnapshotClass, VMS auth, and metrics are included.
Replication and extension-controller features are intentionally excluded.

## Prerequisites
 - [install Helm](https://helm.sh/docs/intro/quickstart/#install-helm)


### Install the GKE version of the driver
```console
helm repo add vast-gke https://raw.githubusercontent.com/vast-data/vast-csi/gke-gh-pages
helm install csi-driver vast-gke/vastcsi-gke -f values.yaml -n vast-csi --create-namespace
```

> **NOTE:** Optionally modify values.yaml or set overrides via Helm command line


### install a specific version
```console
helm install csi-driver vast-gke/vastcsi-gke -f values.yaml -n vast-csi --create-namespace --version 2.7.0
```

### Upgrade driver
```console
helm upgrade csi-driver vast-gke/vastcsi-gke -f values.yaml -n vast-csi
```

### Upgrade helm repository
```console
helm repo update vast-gke
```

### Uninstall driver
```console
helm uninstall csi-driver  -n vast-csi
```

### search for all available chart versions
```console
helm search repo -l vast-gke
```

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
