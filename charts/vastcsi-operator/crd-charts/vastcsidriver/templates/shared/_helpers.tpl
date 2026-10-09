{{/* OLM/operator-specific helpers. */}}

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

{{/*

*/}}
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

{{/*
Shared plugin env. Optional dict override:
  include "vastcsi.commonEnv" .
  include "vastcsi.commonEnv" (dict "root" . "timeout" .Values.csiAddonsSidecar.operationTimeout)
*/}}
{{- define "vastcsi.commonEnv" -}}
{{- $root := .root | default . -}}
{{- $timeout := .timeout | default $root.Values.operationTimeout -}}
{{ "\n" }}{{ include "vast.common.csi.baseEnv" (dict
  "pluginName" (include "vastcsi.csiDriver" $root)
  "pluginLogLevel" ($root.Values.pluginLogLevel | default "info")
  "endpoint" $root.Values.endpoint
  "verifySsl" $root.Values.verifySsl
  "workers" $root.Values.numWorkers
  "timeout" $timeout
  "cacheMaxAge" $root.Values.cacheMaxAgeSeconds
  "disableUsageStats" ($root.Values.disableUsageStats | default false)
) }}
- name: X_CSI_DELETION_VIP_POOL_NAME
  value: {{ $root.Values.deletionVipPool | quote }}
- name: X_CSI_DELETION_VIEW_POLICY
  value: {{ $root.Values.deletionViewPolicy | quote }}
- name: X_CSI_DELETION_MOUNT_OPTIONS
  value: {{ $root.Values.deletionMountOptions | quote }}
- name: X_CSI_DONT_USE_TRASH_API
  value: {{ $root.Values.dontUseTrashApi | quote }}
- name: X_CSI_USE_LOCALIP_FOR_MOUNT
  value: {{ $root.Values.useLocalIpForMount | quote }}
- name: X_CSI_MOUNT_UMOUNT_TIMEOUT
  value: {{ $root.Values.mountUmountTimeout | quote }}
- name: X_CSI_FORCE_LAZY_UMOUNT_ON_TIMEOUT
  value: {{ $root.Values.forceLazyUmountOnTimeout | quote }}
{{- if $root.Values.resolveMountSymlinks }}
- name: X_CSI_RESOLVE_MOUNT_SYMLINKS
  value: {{ $root.Values.resolveMountSymlinks | quote }}
{{- end }}
- name: X_CSI_ATTACH_REQUIRED
  value: {{ $root.Values.attachRequired | quote }}
{{- if $root.Values.allowROManyBlockFsMode }}
- name: X_CSI_ALLOW_RO_MANY_BLOCK_FS_MODE
  value: {{ $root.Values.allowROManyBlockFsMode | quote }}
{{- end }}
{{- if $root.Values.truncateVolumeName }}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $root.Values.truncateVolumeName | quote }}
{{- end }}
{{- if $root.Values.truncateSnapshotName }}
- name: X_CSI_TRUNCATE_SNAPSHOT_NAME
  value: {{ $root.Values.truncateSnapshotName | quote }}
{{- end }}
- name: X_CSI_BLOCK_HOSTS_AUTO_PRUNE
  value: {{ $root.Values.blockHostsAutoPrune | quote }}
{{- if $root.Values.hostNamePrefix }}
- name: X_CSI_HOST_NAME_PREFIX
  value: {{ $root.Values.hostNamePrefix | quote }}
{{- end }}
{{- end }}

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
