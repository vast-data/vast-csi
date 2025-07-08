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
{{ if $.Values.truncateVolumeName -}}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
{{- end }}

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


{{- define "vastcsi.dictToKeyValParams" -}}
{{- $input := index . 0 -}}               {{/* The map to render */}}
{{- $prefix := index . 1 | default "" -}} {{/* Optional prefix for keys */}}

{{- if not (kindIs "map" $input) }}
  {{- $errorMsg := printf "Invalid format. Expected a dictionary but got:\n%s" (toYaml $input) }}
  {{- fail $errorMsg }}
{{- else }}
  {{- range $k, $v := $input }}
    {{- if $v }}
      {{- if or (not (kindIs "string" $v)) (ne $v "") }}
{{ printf "%s%s: %s" $prefix $k ($v | quote) }}
      {{- end }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
