{{/* Create chart name and version as used by the chart label. */}}
{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
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

{{- define "vastcsi.csiDriver" -}}
{{- .Values.driverName | required "Driver Name is not provided" -}}
{{- end -}}

{{/* Validate if secret exists. */}}
{{- define "vastcsi.secret" -}}
{{- $secret := $.Values.clusterName -}}
{{- $secret_namespace := $.Release.Namespace -}}
{{- if not $secret -}}
  {{- fail "clusterName is required value. Please specify valid clusterName" -}}
{{- end }}
{{- if $.Release.IsInstall -}}
{{- if not (lookup "v1" "Secret" $secret_namespace $secret) -}}
  {{- fail (printf "cluster '%s' doesn't exist in namespace '%s' or doesn't have underlying secret." .Values.clusterName .Release.Namespace) -}}
{{- end -}}
{{- end -}}
{{- $secret }}
{{- end -}}
