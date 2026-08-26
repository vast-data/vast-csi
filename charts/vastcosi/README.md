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
helm install cosi-driver vast/vastcosi -f values.yaml -n vast-cosi --create-namespace --version 2.6.7
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

### Credentials flattener

Permanent with the COSI driver: Rook-style flat env vars (`AWS_*` / `BUCKET_*`) from annotated `BucketAccess`.

Flattener uses the extensions-controller image (`{csiVastPlugin.tag}-extensions`). Override with `image.vastExtensionController.repository` / `tag` if needed.

Annotate access with `cosi.vastdata.com/flatten-credentials: "true"`. See `examples/cosi/flatten-credentials.yaml`.

**RBAC / security:** The flattener uses a **ClusterRole** (not a namespaced Role) because `BucketAccess` objects and their credential Secrets can live in application namespaces while the flattener pod runs in the COSI driver namespace — same pattern as the COSI provisioner. That SA can **get/list/watch/create/update/patch/delete Secrets and ConfigMaps in every namespace** on the cluster. The flattener creates sibling `*-flat` objects only for `BucketAccess` annotated with `cosi.vastdata.com/flatten-credentials: "true"`; it does not read arbitrary Secrets. Flat objects duplicate credentials (another copy in the namespace); treat `*-flat` Secrets like the source COSI credential Secret.

### Writable bucket clones (BucketClaim annotations)

Permanent: the extensions-manager sidecar merges per-claim `cosi.vastdata.com/*` annotations into `Bucket.spec.parameters` before provisioning.

Annotate `BucketClaim` (not `BucketClass`):

- `cosi.vastdata.com/sourceBucket: <source-s3-bucket-name>` (selects clone mode)
- `cosi.vastdata.com/blockingClones: "true"` (optional; wait for GSS completion)

See `examples/cosi/cosi-bucket-clone.yaml`.

### Per-bucket quota (BucketClaim annotations)

The bucket-params webhook also passes claim-level quota overrides. Annotate `BucketClaim` with `cosi.vastdata.com/maxSize` (claim wins over BucketClass `max_size` from VCSI-261):

```yaml
metadata:
  annotations:
    cosi.vastdata.com/maxSize: "5Gi"
```

See `examples/cosi/bucketclaim-quota.yaml`.

### search for all available chart versions
```console
helm search repo -l vast
```

### troubleshooting
 - Add `--wait -v=5 --debug` in `helm install` command to get detailed error
 - Use `kubectl describe` to acquire more info

## Multitenancy (per-BucketClass VMS credentials)

COSI supports per-BucketClass VMS credentials via `secretName` /
`secretNamespace` Helm keys (same naming as other charts). The chart emits
`vastdata.com/secret-name` and `vastdata.com/secret-namespace` on the BucketClass.
Create uses those parameters directly; delete, grant, and revoke resolve the same
credentials via `ResolveCOSIBucketAuth`, which looks up the Bucket CR by `bucket_id`
and reads the persisted secret ref — without embedding secrets in `bucket_id`.
If the Bucket has no secret refs (pre-multitenancy buckets), auth falls back to the
chart-level mounted secret at `/opt/vms-auth`.

### VMS auth Secret shape

Create a Kubernetes Secret in the namespace referenced by the BucketClass (or the Helm
release namespace when `secretNamespace` is omitted):

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: team-a-vast-auth
  namespace: app-team
stringData:
  endpoint: vms.example.com
  token: <API token>          # token-only auth
  tenant: team-a              # optional; omit or leave empty for cluster-admin
```

Username/password auth is also supported (`username`, `password`, optional `tenant`).

### BucketClass parameters

In Helm `bucketClasses`, set `secretName` and optionally `secretNamespace`
(defaults to the release namespace). Choose **either** `vipPool` (VMS resolves a VIP)
**or** `vipPoolFQDN` (DNS endpoint; skips the VIP lookup). Use
`vipPoolFQDNRandomPrefix: true` to prepend a random subdomain per bucket.

```yaml
bucketClasses:
  team-a-buckets:
    storagePath: /cosi/team-a
    viewPolicy: s3-policy-team-a
    secretName: team-a-vast-auth
    secretNamespace: app-team
    vipPoolFQDN: s3-team-a.example.com
    scheme: https
```

The rendered BucketClass includes:

```yaml
parameters:
  vastdata.com/secret-name: team-a-vast-auth
  vastdata.com/secret-namespace: app-team
```

> **NOTE:** BucketClass parameters are immutable. Adding `secretName` to an existing
> BucketClass requires recreating the BucketClass and any buckets provisioned from it.

### Legacy single-tenant installs

Set the chart-level `secretName` value to mount global credentials at `/opt/vms-auth`.
BucketClasses without per-class `secretName` continue to use that fallback for create.
Delete, grant, and revoke on buckets that never stored secret refs on the Bucket CR
also fall back to `/opt/vms-auth`, so upgrading the driver does not break lifecycle
of pre-multitenancy buckets when the chart secret is still mounted.
For multitenant clusters, leave chart `secretName` empty and configure secrets per
BucketClass instead.
