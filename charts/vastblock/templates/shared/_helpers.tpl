{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}


{{- define "vastcsi.csiDriver" -}}
{{- coalesce $.Values.csiDriverName "block.csi.vastdata.com" -}}
{{- end -}}


{{- define "vastcsi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}


{{- define "vastcsi.commonArgs" -}}
- "--csi-address=$(ADDRESS)"
- "--v={{ .Values.logLevel | default 5 }}"
{{- end }}


{{- define "vastcsi.namespace" -}}
{{- coalesce $.Release.Namespace "vast-csi" | quote -}}
{{- end }}


{{- define "vastcsi.commonEnv" }}

- name: X_CSI_PLUGIN_NAME
  value: {{ include "vastcsi.csiDriver" $ | quote }}
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | default "" |  quote }}
- name: X_CSI_ENABLE_VMS_SSL_VERIFICATION
  value: {{ $.Values.verifySsl | quote }}
- name: X_CSI_WORKER_THREADS
  value: {{ $.Values.numWorkers | quote }}
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
- name: X_CSI_BLOCK_HOSTS_AUTO_PRUNE
  value: {{ $.Values.blockHostsAutoPrune | quote }}

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


{{/*
Renders a key-value pair where the value is the input map serialized to a JSON string.

Inputs:
- .0: map to serialize (must be of type "map")
- .1: key to associate with the JSON string

Result:
<key>: "<JSON-string>"

Fails if the input is not a map.
*/}}
{{- define "vastcsi.dictToJsonStringParam" -}}
{{- $map := index . 0 -}}
{{- $key := index . 1 -}}
{{- if not (kindIs "map" $map) }}
  {{- $errorMsg := printf "Invalid format. Expected a map for JSON serialization but got:\n%s" (toYaml $map) }}
  {{- fail $errorMsg }}
{{- else }}
{{ $key }}: {{ $map | toJson | quote }}
{{- end }}
{{- end }}
