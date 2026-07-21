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
helm install cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --create-namespace --version 2.6.6
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

### Optional: credentials flattener

Enable Rook-style flat env vars (`AWS_*` / `BUCKET_*`) from annotated `BucketAccess`:

```console
helm upgrade cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --set credsFlattener.enabled=true
```

Flattener uses the extensions-controller image (`{csiVastPlugin.tag}-extensions`). Override with `image.vastExtensionController.repository` / `tag` if needed.

Annotate access with `cosi.vastdata.com/flatten-credentials: "true"`. See `examples/cosi/flatten-credentials.yaml`.

**RBAC / security:** The flattener uses a **ClusterRole** (not a namespaced Role) because `BucketAccess` objects and their credential Secrets can live in application namespaces while the flattener pod runs in the COSI driver namespace — same pattern as the COSI provisioner. That SA can **get/list/watch/create/update/patch/delete Secrets and ConfigMaps in every namespace** on the cluster. Only enable it when that blast radius is acceptable. The flattener creates sibling `*-flat` objects only for `BucketAccess` annotated with `cosi.vastdata.com/flatten-credentials: "true"`; it does not read arbitrary Secrets. Flat objects duplicate credentials (another copy in the namespace); treat `*-flat` Secrets like the source COSI credential Secret.

### search for all available chart versions
```console
helm search repo -l vast
```

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info
