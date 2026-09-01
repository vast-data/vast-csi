# VAST common Helm library

`vast-common` is a private implementation dependency of the public VAST charts. It does
not install resources by itself (`values.yaml` is comment-only). Consumers should use
only the documented `vast.common.*` named templates below and pass explicit dictionaries
to resource factories.

## Versioning and release

The library is versioned independently of the public charts and is published to the same
Helm repository (`https://vast-data.github.io/vast-csi`), which the public charts declare as
the `vast-common` dependency repository. Release CI does not stamp this chart's version.

Templates are split by concern under `templates/`:

- `_names.tpl`, `_labels.tpl` — metadata
- `_capabilities.tpl` — Kubernetes/Helm version and apiVersion helpers
- `_openshift.tpl` — OpenShift detection and platform-specific helpers
- `_extensions.tpl` — CRD installation guards for extensions/replication
- `_tplvalues.tpl`, `_params.tpl`, `_images.tpl` — rendering, serialization, pull secrets
- `_secrets.tpl` — secret lookup and existence checks
- `_utils.tpl` — nested values path utilities
- `_csi.tpl`, `_vms-auth.tpl` — CSI/VMS fragments
- `_resources.tpl` — named resource factories

## Metadata

- `vast.common.name`, `vast.common.chart`, `vast.common.namespace`
- `vast.common.selectorLabels`, `vast.common.labels`

These accept the chart root context and preserve the public charts' existing naming and
label conventions.

## Capabilities

Cluster-aware helpers for version checks and stable apiVersion selection. Not yet wired
into the public charts; use these when adding version-sensitive templates.

- `vast.common.capabilities.kubeVersion`: root context. Effective Kubernetes version
- `vast.common.capabilities.versionCompare`: `dict "root" $ "constraint" CONSTRAINT`.
  Semver check against the effective Kubernetes version
- `vast.common.capabilities.apiVersions.has`: `dict "version" API_VERSION "root" $`.
  Whether an API version is available (honours optional `.Values.apiVersions` /
  `.Values.global.apiVersions` overrides for offline rendering)
- `vast.common.capabilities.supportsHelmVersion`: root context. True on Helm 3.3+
- `vast.common.capabilities.deployment.apiVersion`, `.daemonset.apiVersion`,
  `.rbac.apiVersion`, `.crd.apiVersion`, `.storage.apiVersion`, `.snapshot.apiVersion`,
  `.admissionRegistration.apiVersion`, `.policy.apiVersion`, `.serviceMonitor.apiVersion`:
  root context. Stable apiVersion strings for common resource kinds

## OpenShift

- `vast.common.openshift.isOpenshift`: root context. True when
  `security.openshift.io/v1` is available

## Extensions

- `vast.common.extensions.shouldInstallCRD`: `dict "root" $ "crdName" NAME`. Returns
  `"true"` when the chart should emit a CRD (missing, or already owned by the current
  release). Skips CRDs owned by another Helm release

## Rendering and serialization

- `vast.common.tpl.render`: `dict "root" $ "value" VALUE`
- `vast.common.params.keyValue`: `dict "values" MAP`
- `vast.common.params.bool`: `dict "values" MAP`. Emits recognized true and false values
- `vast.common.params.json`: `dict "value" VALUE "key" KEY`
- `vast.common.image`: `dict "root" $ "image" IMAGE`. Requires and renders both
  `IMAGE.repository` and `IMAGE.tag` through `vast.common.tpl.render`, then emits
  `repository:tag`
- `vast.common.imagePullSecrets`: `dict "secrets" LIST`

## Secrets

Cluster lookup helpers. Require a live cluster (`lookup` does not work with offline
`helm template`).

- `vast.common.secrets.lookup`: `dict "root" $ "secret" NAME "key" KEY "defaultValue" VALUE`.
  Returns existing base64 secret data, or base64-encodes `defaultValue` when the secret or
  key is missing
- `vast.common.secrets.exists`: `dict "root" $ "secret" NAME`. Returns `"true"` when the
  secret already exists in the release namespace

## Utils

- `vast.common.utils.getValueFromKey`: `dict "root" $ "key" "path.to.key"`. Returns a
  nested value from `.Values`
- `vast.common.utils.getKeyFromList`: `dict "root" $ "keys" (list "path.one" "path.two")`.
  Returns the first key with a defined value, or the first key if none are defined

## CSI and VMS fragments

- `vast.common.csi.driverName`: root context, reads `.Values.csiDriverName`. Required, with
  no default; charts must set the value
- `vast.common.csi.verbosityArg`: root context, reads `.Values.logLevel`. Emits only the
  klog `--v` flag, for containers that take verbosity but not a plugin socket address
- `vast.common.csi.args`: root context. Full sidecar arg set: plugin socket address plus
  `verbosityArg`
- `vast.common.csi.baseEnv`: explicit `pluginName`, `pluginLogLevel`, `endpoint`,
  `verifySsl`, `workers`, `timeout`, `cacheMaxAge`, `disableUsageStats`, and optional
  `extraEnv`. Covers the env vars every chart emits identically, both VMS session settings
  and plugin runtime settings
- `vast.common.vmsAuth.volumes` / `vast.common.vmsAuth.volumeMounts`: root context, read
  `secretName`, `sslCert`, `sslCertsSecretName`, and `verifySsl`. The CA bundle secret is
  derived by `vast.common.vmsAuth.caBundle`, and the conflicting-certificate and
  `verifySsl` guards are enforced here
- `vast.common.credSerde.volume` / `vast.common.credSerde.volumeMount`: root context, read
  `credSerializationSecret`

The four volume and volume-mount templates emit a leading newline only when they produce
content, so call sites are written as `{{- include "..." . | indent N }}` directly after a
list item and leave no blank line behind when nothing is mounted.

## Resource factories

All factories require dictionaries. Callers own feature gates and chart-specific policy.

- `vast.common.resource.csiDriver`
- `vast.common.resource.serviceAccount`
- `vast.common.resource.sslSecret`
- `vast.common.resource.metricsService`
- `vast.common.resource.serviceMonitor`
- `vast.common.resource.webhookService`
- `vast.common.resource.webhookCertificate`

Factories intentionally expose names, namespaces, labels, selectors, and other mutable
fields rather than deriving chart-specific semantics.
