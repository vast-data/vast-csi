# Install CSI driver with Helm 3

## Prerequisites
 - [install Helm](https://helm.sh/docs/intro/quickstart/#install-helm)


### install production version of the driver:
```console
helm repo add vast https://vast-data.github.io/vastcsi
helm install csi-driver vast/vastcsi -f values.yaml -n vast-csi --create-namespace
```

### install beta version of the driver:
```console
helm repo add vast https://raw.githubusercontent.com/vast-data/vast-csi/gh-pages-beta
helm install csi-driver vast/vastcsi -f values.yaml -n vast-csi --create-namespace
```

> **NOTE:** Optionally modify values.yaml or set overrides via Helm command line 


### install a specific version
```console
helm install csi-driver vast/vastcsi -f values.yaml -n vast-csi --create-namespace --version 2.3.0
```

### Upgrade driver
```console
helm upgrade csi-driver vast/vastcsi -f values.yaml -n vast-csi
```

### Upgrade helm repository
```console
helm repo update vast
```

### Uninstall driver
```console
helm uninstall csi-driver  -n vast-csi
```

### search for all available chart versions
```console
helm search repo -l vast
```

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
