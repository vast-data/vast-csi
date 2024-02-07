{{/* Common labels and selectors */}}

{{- define "vastcosiname" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}


{{/* Common labels */}}
{{- define "vastcosilabels" -}}
helm.sh/chart: {{ include "vastcosichart" . }}
{{ include "vastcosiselectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}


{{/* Common selectors */}}
{{- define "vastcosiselectorLabels" -}}
app.kubernetes.io/name: {{ include "vastcosiname" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
