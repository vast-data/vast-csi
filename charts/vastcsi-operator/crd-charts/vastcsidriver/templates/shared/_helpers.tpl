{{- /*
# IMPORTANT: cosi and csi helm charts share similar templates.
# If you make changes to a template in one chart, make sure to replicate those
# changes in the corresponding template in the other chart.
*/}}

{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastcsi.commonArgs" -}}
- "--csi-address=$(ADDRESS)"
- "--v={{ .Values.logLevel | default 5 }}"
{{- end }}

{{- define "vastcsi.namespace" -}}
{{- quote (coalesce $.Release.Namespace "vast-csi") -}}
{{- end }}

{{- define "vastcsi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastcsi.dnsSafeReleaseName" -}}
{{- .Release.Name | replace "." "-" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "vastcsi.workloadNamePrefix" -}}
{{- ternary "csi" "block" (eq .Values.driverType "nfs") -}}
{{- end }}

{{/*
Normalize node.nfsServices.services for Helm and OLM UI.
The console may store a single array element like "statd rpcbind" instead of ["statd", "rpcbind"].
*/}}
{{- define "vastcsi.nfsServicesArg" -}}
{{- join "," (compact (splitList " " (join " " (default list .Values.node.nfsServices.services)))) -}}
{{- end -}}

{{/* Common labels */}}
{{- define "vastcsi.labels" -}}
helm.sh/chart: {{ include "vastcsi.chart" . }}
{{ include "vastcsi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
storage.vastdata.com/driverType: {{ .Values.driverType }}
{{- end }}

{{/* Common selectors */}}
{{- define "vastcsi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vastcsi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "vastcsi.csiDriver" -}}
{{- $default_driver_name := ternary "csi.vastdata.com" "block.csi.vastdata.com" (eq $.Values.driverType "nfs") -}}
{{- coalesce .Release.Name $default_driver_name -}}
{{- end -}}

{{/*
Resolve a component container image.

By default, prefer defaultRepository (OLM RELATED_IMAGE_* injected via watches.yaml)
over CR spec.image.*.repository.
Set image.useCustomRepositories=true to force CR repository overrides (air-gap / custom builds).

Usage: {{ include "vastcsi.resolvedImage" (dict "ctx" . "img" $csi_images.csiVastPlugin) }}
*/}}
{{- define "vastcsi.resolvedImage" -}}
{{- $img := .img -}}
{{- if .ctx.Values.image.useCustomRepositories -}}
{{- coalesce $img.repository $img.defaultRepository -}}
{{- else -}}
{{- coalesce $img.defaultRepository $img.repository -}}
{{- end -}}
{{- end -}}

{{- define "vastcsi.commonEnv" }}
- name: X_CSI_PLUGIN_NAME
  value: {{ include "vastcsi.csiDriver" $ | quote }}
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | default "" | quote }}
- name: X_CSI_ENABLE_VMS_SSL_VERIFICATION
  value: {{ $.Values.verifySsl | quote }}
- name: X_CSI_DELETION_VIP_POOL_NAME
  value: {{ $.Values.deletionVipPool | quote }}
- name: X_CSI_DELETION_VIEW_POLICY
  value: {{ $.Values.deletionViewPolicy | quote }}
- name: X_CSI_WORKER_THREADS
  value: {{ $.Values.numWorkers | quote }}
- name: X_CSI_DONT_USE_TRASH_API
  value: {{ $.Values.dontUseTrashApi | quote }}
- name: X_CSI_USE_LOCALIP_FOR_MOUNT
  value: {{ $.Values.useLocalIpForMount | quote }}
- name: X_CSI_ATTACH_REQUIRED
  value: {{ $.Values.attachRequired | quote }}
- name: X_CSI_DISABLE_USAGE_STATS
  value: {{ $.Values.disableUsageStats | default false | quote }}
- name: X_CSI_CACHE_MAX_AGE
  value: {{ $.Values.cacheMaxAgeSeconds | default 0 | quote }}
- name: X_CSI_MOUNT_UMOUNT_TIMEOUT
  value: {{ $.Values.mountUmountTimeout | quote }}
- name: X_CSI_FORCE_LAZY_UMOUNT_ON_TIMEOUT
  value: {{ $.Values.forceLazyUmountOnTimeout | quote }}
{{- if $.Values.resolveMountSymlinks }}
- name: X_CSI_RESOLVE_MOUNT_SYMLINKS
  value: {{ $.Values.resolveMountSymlinks | quote }}
{{- end }}
{{- if $.Values.allowROManyBlockFsMode }}
- name: X_CSI_ALLOW_RO_MANY_BLOCK_FS_MODE
  value: {{ $.Values.allowROManyBlockFsMode | quote }}
{{- end }}
{{- if $.Values.truncateVolumeName }}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
{{- end }}
{{- if $.Values.truncateSnapshotName }}
- name: X_CSI_TRUNCATE_SNAPSHOT_NAME
  value: {{ $.Values.truncateSnapshotName | quote }}
{{- end }}
- name: X_CSI_BLOCK_HOSTS_AUTO_PRUNE
  value: {{ $.Values.blockHostsAutoPrune | quote }}
{{- if $.Values.hostNamePrefix }}
- name: X_CSI_HOST_NAME_PREFIX
  value: {{ $.Values.hostNamePrefix | quote }}
{{- end }}

{{- end }}


{{/*
Build the comma-separated list of addons to enable.
VolumeGroupReplicationClass is always created alongside VolumeReplicationClass.
Usage:
{{- include "vastcsi.addons-list" (dict "root" . "type" "nfs") -}}
*/}}
{{- define "vastcsi.addons-list" -}}
{{- $type := .type -}}
{{- join "," (list (printf "replication[%s]" $type) (printf "volumegroup[%s]" $type)) -}}
{{- end -}}

{{- define "vastcsi.fallbackToDeserEnv" -}}
{{- if not (kindIs "bool" .Values.fallbackToDeser) }}
{{- fail "fallbackToDeser must be set explicitly to true or false" }}
{{- end }}
- name: X_CSI_FALLBACK_TO_DESER
  value: {{ .Values.fallbackToDeser | quote }}
{{- end }}

{{/*
True when node.nfsServices.tlshd ConfigMap and certificates.secretName are both set.
*/}}
{{- define "vastcsi.nfsServicesTlshdOverridesEnabled" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if and $tlshd.configMap ($certs.secretName | default "") -}}
true
{{- end -}}
{{- end -}}

{{/*
TLS / tlshd sidecar volumes for csi-nfs-services (NFS-over-TLS / mTLS).
ConfigMap (tlshd.conf) and Secret (PEM files) must live in the node pod namespace.
*/}}
{{- define "vastcsi.nfsServicesTlshdVolumeMounts" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if $tlshd.configMap }}
- name: tlshd-conf
  mountPath: /etc/tlshd.conf
  subPath: tlshd.conf
  readOnly: true
{{- else }}
- name: tlshd-conf
  mountPath: /etc/tlshd.conf
  readOnly: true
{{- end }}
{{- if $certs.secretName }}
- name: tlshd-certs
  mountPath: {{ $certs.mountPath | default "/etc/vast-tlshd" }}
  readOnly: true
{{- end }}
{{- end -}}

{{- define "vastcsi.nfsServicesTlshdVolumes" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if and $tlshd.configMap (not $certs.secretName) }}
{{- fail "node.nfsServices.tlshd: certificates.secretName is required when configMap is set" }}
{{- end }}
{{- if and ($certs.secretName) (not $tlshd.configMap) }}
{{- fail "node.nfsServices.tlshd: configMap is required when certificates.secretName is set" }}
{{- end }}
{{- if $tlshd.configMap }}
- name: tlshd-conf
  configMap:
    name: {{ $tlshd.configMap }}
    defaultMode: 0444
{{- else }}
- name: tlshd-conf
  hostPath:
    path: /etc/tlshd.conf
    type: File
{{- end }}
{{- if $certs.secretName }}
- name: tlshd-certs
  secret:
    secretName: {{ $certs.secretName }}
    defaultMode: 0444
{{- end }}
{{- end -}}
