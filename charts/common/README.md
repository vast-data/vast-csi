# VAST common Helm library

`vast-common` is a private implementation dependency of the public VAST charts. It does
not install resources by itself (`values.yaml` is comment-only). Consumers should use
only the documented `vast.common.*` named templates below and pass explicit dictionaries
to resource factories.

## Versioning and release

The library is versioned independently of the public charts and is published to the same
Helm repository (`https://vast-data.github.io/vast-csi`), which the public charts declare as
the `vast-common` dependency repository. Release CI does not stamp this chart's version.

To ship a change: bump `version` in `Chart.yaml`, then run the manual `release_common_chart`
GitLab job (`scripts/release_common_chart.sh`). It refuses to publish a version that already
exists in the index. Because the public charts resolve the dependency remotely, the new
version must be published **before** they can pin it, so raise the dependency `version` in
`charts/*/Chart.yaml` and refresh the locks with `make chart-deps-update` afterwards.

Templates are split by concern under `templates/`:

- `_names.tpl`, `_labels.tpl` — metadata
- `_tplvalues.tpl`, `_params.tpl`, `_images.tpl` — rendering, serialization, pull secrets
- `_csi.tpl`, `_vms-auth.tpl` — CSI/VMS fragments
- `_resources.tpl` — named resource factories

## Metadata

- `vast.common.name`, `vast.common.chart`, `vast.common.namespace`
- `vast.common.selectorLabels`, `vast.common.labels`

These accept the chart root context and preserve the public charts' existing naming and
label conventions.

## Rendering and serialization

- `vast.common.tpl.render`: `dict "root" $ "value" VALUE`
- `vast.common.params.keyValue`: `dict "values" MAP`
- `vast.common.params.bool`: `dict "values" MAP`. Emits recognized true and false values
- `vast.common.params.json`: `dict "value" VALUE "key" KEY`
- `vast.common.image`: `dict "root" $ "image" IMAGE`. Requires and renders both
  `IMAGE.repository` and `IMAGE.tag` through `vast.common.tpl.render`, then emits
  `repository:tag`
- `vast.common.imagePullSecrets`: `dict "secrets" LIST`

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
