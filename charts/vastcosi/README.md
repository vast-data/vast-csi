# Install COSI driver with Helm 3

## Prerequisites
 - [install Helm](https://helm.sh/docs/intro/quickstart/#install-helm)


### install production version of the driver:
```console
helm repo add vast https://vast-data.github.io/vastcsi
helm install cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --create-namespace
```

### install beta version of the driver:
```console
helm repo add vast https://raw.githubusercontent.com/vast-data/vast-csi/gh-pages-beta
helm install cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --create-namespace
```

> **NOTE:** Optionally modify values.yaml or set overrides via Helm command line 


### install a specific version
```console
helm install cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --create-namespace --version 2.4.0
```

### Upgrade driver
```console
helm upgrade cosi-driver vast/vastcosi -f values.yaml -n vast-cosi
```

### Upgrade helm repository
```console
helm repo update vast
```

### Uninstall driver
```console
helm uninstall cosi-driver  -n vast-cosi
```

### search for all available chart versions
```console
helm search repo -l vast
```

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
