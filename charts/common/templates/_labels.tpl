{{/*
Standard Kubernetes labels and selector labels. Input is the consuming chart root context.
*/}}

{{- define "vast.common.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vast.common.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{- define "vast.common.labels" -}}
helm.sh/chart: {{ include "vast.common.chart" . }}
{{ include "vast.common.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
