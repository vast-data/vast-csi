{{/*
Construct image names from Values.
For VAST CLI plugin, take .Chart.appVersion as the image tag unless overridden.
*/}}
{{- define "vastcsi.csiAttacherImage" -}}
{{- printf "%s:%s" .Values.image.csiAttacher.repository .Values.image.csiAttacher.tag }}
{{- end }}

{{- define "vastcsi.csiNodeDriverRegistrarImage" -}}
{{- printf "%s:%s" .Values.image.csiNodeDriverRegistrar.repository .Values.image.csiNodeDriverRegistrar.tag }}
{{- end }}

{{- define "vastcsi.csiPluginVastImage" -}}
{{- $tag := default .Chart.AppVersion .Values.image.csiPluginVast.tag }}
{{- printf "%s:%s" .Values.image.csiPluginVast.repository $tag }}
{{- end }}

{{- define "vastcsi.csiProvisionerImage" -}}
{{- printf "%s:%s" .Values.image.csiProvisioner.repository .Values.image.csiProvisioner.tag }}
{{- end }}

{{- define "vastcsi.csiResizerImage" -}}
{{- printf "%s:%s" .Values.image.csiResizer.repository .Values.image.csiResizer.tag }}
{{- end }}

{{/*
Expand the name of the chart.
*/}}
{{- define "vastcsi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "vastcsi.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "vastcsi.labels" -}}
helm.sh/chart: {{ include "vastcsi.chart" . }}
{{ include "vastcsi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "vastcsi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vastcsi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "vastcsi.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "vastcsi.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
