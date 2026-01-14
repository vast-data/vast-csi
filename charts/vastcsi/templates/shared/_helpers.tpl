{{/*Create chart name and version as used by the chart label.*/}}

{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastcsi.commonArgs" -}}
- "--csi-address=$(ADDRESS)"
- "--v={{ .Values.logLevel | default 5 }}"
{{- end }}

{{- /*
# IMPORTANT: cosi and csi helm charts share similar templates.
# If you make changes to a template in one chart, make sure to replicate those
# changes in the corresponding template in the other chart.
*/}}

{{- define "vastcsi.csiDriver" -}}
{{- coalesce $.Values.csiDriverName "csi.vastdata.com" -}}
{{- end -}}

{{- define "vastcsi.commonEnv" }}
- name: X_CSI_PLUGIN_NAME
  value: {{ include "vastcsi.csiDriver" $ | quote }}
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | default "" |  quote }}
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
- name: X_CSI_VMS_TIMEOUT
  value: {{ $.Values.operationTimeout | quote }}
- name: X_CSI_CACHE_MAX_AGE
  value: {{ $.Values.cacheMaxAgeSeconds | default 0 | quote }}
- name: X_CSI_DISABLE_USAGE_STATS
  value: {{ $.Values.disableUsageStats | quote }}
{{ if $.Values.truncateVolumeName -}}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
{{- end }}
{{- end }}

{{- define "vastcsi.namespace" -}}
{{- coalesce $.Release.Namespace "vast-csi" | quote -}}
{{- end }}

{{/* Common labels and selectors */}}

{{- define "vastcsi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Common labels */}}
{{- define "vastcsi.labels" -}}
helm.sh/chart: {{ include "vastcsi.chart" . }}
{{ include "vastcsi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Common selectors */}}
{{- define "vastcsi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vastcsi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Renders key-value pairs for CSI parameters.
- Quotes all values except ints.
- Skips empty values.

Usage: include "vastcsi.dictToKeyValParams" (dict $your_dict)
*/}}
{{- define "vastcsi.dictToKeyValParams" -}}
{{- $input := index . 0 -}}
  {{- range $key, $value := $input }}
    {{- if and $value (ne $value (quote "")) }}
{{ $key }}: {{ if kindIs "int" $value }}{{ $value | quote }}{{ else }}{{ $value }}{{ end }}
    {{- end }}
  {{- end }}
{{- end }}


{{/*
Renders key-value pairs where the value is interpreted as boolean true.
Truthy values include:
- bool true
- strings: "true", "1", "on" (case-insensitive, trims quotes)

Result: key: "true"
*/}}
{{- define "vastcsi.dictToBoolParams" -}}
{{- $input := index . 0 -}}
{{- range $key, $value := $input }}
  {{- if kindIs "bool" $value }}
    {{- if $value }}
{{ $key }}: "true"
    {{- end }}
  {{- else }}
    {{- $normalized := trimAll "\"" (toString $value) | lower }}
    {{- if or (eq $normalized "true") (eq $normalized "1") (eq $normalized "on") }}
{{ $key }}: "true"
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
