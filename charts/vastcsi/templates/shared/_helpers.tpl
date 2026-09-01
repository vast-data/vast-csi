{{/* Chart-specific helpers. Generic naming, labels, and env primitives come from vast-common. */}}

{{- define "vastcsi.commonEnv" -}}
{{- $root := .root | default . -}}
{{- $timeout := .timeout | default $root.Values.operationTimeout -}}
{{ "\n" }}{{ include "vast.common.csi.baseEnv" (dict
  "pluginName" (include "vast.common.csi.driverName" $root)
  "pluginLogLevel" $root.Values.pluginLogLevel
  "endpoint" $root.Values.endpoint
  "verifySsl" $root.Values.verifySsl
  "workers" $root.Values.numWorkers
  "timeout" $timeout
  "cacheMaxAge" $root.Values.cacheMaxAgeSeconds
  "disableUsageStats" $root.Values.disableUsageStats
) }}
- name: X_CSI_DELETION_VIP_POOL_NAME
  value: {{ $root.Values.deletionVipPool | quote }}
- name: X_CSI_DELETION_VIEW_POLICY
  value: {{ $root.Values.deletionViewPolicy | quote }}
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
{{- if $root.Values.truncateVolumeName }}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $root.Values.truncateVolumeName | quote }}
{{- end }}
- name: X_CSI_FALLBACK_TO_DESER
  value: {{ $root.Values.fallbackToDeser | quote }}
{{- range $key, $value := .extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "vastcsi.addons-list" -}}{{ join "," (list (printf "replication[%s]" .type) (printf "volumegroup[%s]" .type)) }}{{- end -}}
