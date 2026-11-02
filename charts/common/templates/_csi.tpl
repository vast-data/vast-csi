{{/*
CSI sidecar argument and shared plugin environment primitives.
The arg helpers take the consuming chart root context and read .Values.logLevel.
baseEnv takes an explicit dictionary; chart-specific env vars stay in application charts.
*/}}

{{/* Driver name registered with Kubernetes. Input is the chart root context. */}}
{{- define "vast.common.csi.driverName" -}}
{{- required "csiDriverName is required" .Values.csiDriverName -}}
{{- end -}}

{{/* klog verbosity flag for sidecar containers. Input is the chart root context. */}}
{{- define "vast.common.csi.verbosityArg" -}}
- "--v={{ .Values.logLevel | default 5 }}"
{{- end -}}

{{/* Full argument set for upstream CSI sidecars that talk to the plugin socket. */}}
{{- define "vast.common.csi.args" -}}
- "--csi-address=$(ADDRESS)"
{{ include "vast.common.csi.verbosityArg" . }}
{{- end -}}

{{- define "vast.common.csi.baseEnv" -}}
- name: X_CSI_PLUGIN_NAME
  value: {{ .pluginName | quote }}
- name: X_CSI_LOG_LEVEL
  value: {{ .pluginLogLevel | default "info" | quote }}
- name: X_CSI_VMS_HOST
  value: {{ .endpoint | default "" | quote }}
- name: X_CSI_ENABLE_VMS_SSL_VERIFICATION
  value: {{ .verifySsl | quote }}
- name: X_CSI_WORKER_THREADS
  value: {{ .workers | quote }}
{{- if hasKey . "timeout" }}
- name: X_CSI_VMS_TIMEOUT
  value: {{ .timeout | quote }}
{{- end }}
- name: X_CSI_CACHE_MAX_AGE
  value: {{ .cacheMaxAge | default 0 | quote }}
- name: X_CSI_DISABLE_USAGE_STATS
  value: {{ .disableUsageStats | quote }}
{{- /*
glibc keeps freed blocks in a per-thread cache (tcache) and never puts them back
on the shared heap, so RssAnon climbs across provisioning waves after the plugin
has already freed everything. tcache_count=0 makes free() return those blocks,
and arena_max=1 makes the gRPC workers share one heap so the blocks get reused.
*/}}
{{- if not (hasKey (.extraEnv | default dict) "GLIBC_TUNABLES") }}
- name: GLIBC_TUNABLES
  value: "glibc.malloc.arena_max=1:glibc.malloc.tcache_count=0:glibc.malloc.tcache_max=0"
{{- end }}
{{- range $key, $value := .extraEnv }}
- name: {{ $key }}
  value: {{ $value | quote }}
{{- end }}
{{- end -}}
