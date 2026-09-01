{{/*
Naming helpers. Input is the consuming chart root context.
*/}}

{{- define "vast.common.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "vast.common.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "vast.common.namespace" -}}
{{- coalesce .Release.Namespace "vast-csi" | quote -}}
{{- end -}}
