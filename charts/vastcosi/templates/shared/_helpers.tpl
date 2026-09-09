{{/* Chart-specific helpers. Generic naming, labels, and env primitives come from vast-common. */}}

{{- define "vastcosicommonEnv" -}}
{{ "\n" }}{{ include "vast.common.csi.baseEnv" (dict
  "pluginName" (include "vast.common.csi.driverName" .)
  "pluginLogLevel" .Values.pluginLogLevel
  "endpoint" .Values.endpoint
  "verifySsl" .Values.verifySsl
  "workers" .Values.numWorkers
  "cacheMaxAge" .Values.cacheMaxAgeSeconds
  "disableUsageStats" .Values.disableUsageStats
) }}
{{- end -}}
