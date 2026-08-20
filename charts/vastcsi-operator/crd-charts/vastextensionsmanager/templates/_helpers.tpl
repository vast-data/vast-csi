{{/* Create chart name and version as used by the chart label. */}}
{{- define "vastextensionsmanager.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Target namespace for extensions manager resources.
*/}}
{{- define "vastextensionsmanager.namespace" -}}
{{- quote (coalesce $.Release.Namespace "vast-csi") -}}
{{- end }}

{{- define "vastextensionsmanager.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastextensionsmanager.dnsSafeReleaseName" -}}
{{- .Release.Name | replace "." "-" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "vastextensionsmanager.deploymentName" -}}
{{- include "vastextensionsmanager.dnsSafeReleaseName" . -}}
{{- end }}

{{- define "vastextensionsmanager.webhookServiceName" -}}
{{- printf "%s-webhook" (include "vastextensionsmanager.dnsSafeReleaseName" .) -}}
{{- end }}

{{- define "vastextensionsmanager.grpcServiceName" -}}
extensions-manager-grpc
{{- end }}

{{- define "vastextensionsmanager.grpcPort" -}}
9090
{{- end }}

{{- define "vastextensionsmanager.webhookTLSSecretName" -}}
{{- printf "%s-tls" (include "vastextensionsmanager.webhookServiceName" .) -}}
{{- end }}

{{- define "vastextensionsmanager.webhookCertificateName" -}}
{{- $default := printf "%s-cert" (include "vastextensionsmanager.webhookServiceName" .) -}}
{{- default $default .Values.webhook.certManager.certificateRef.name -}}
{{- end }}

{{- define "vastextensionsmanager.webhookInjectCAFrom" -}}
{{- $ns := default (include "vastextensionsmanager.namespace" . | trimAll "\"") .Values.webhook.certManager.certificateRef.namespace -}}
{{- printf "%s/%s" $ns (include "vastextensionsmanager.webhookCertificateName" .) -}}
{{- end }}

{{- define "vastextensionsmanager.labels" -}}
helm.sh/chart: {{ include "vastextensionsmanager.chart" . }}
{{ include "vastextensionsmanager.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/component: vast-extensions-manager
{{- end }}

{{- define "vastextensionsmanager.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vastextensionsmanager.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "vastextensionsmanager.pvc-labels-webhook-enabled" -}}
{{- if .Values.replication.webhooks.pvcLabels.enabled -}}
true
{{- end -}}
{{- end }}

{{- define "vastextensionsmanager.vscr-validation-webhook-enabled" -}}
{{- if .Values.replication.webhooks.vastStorageClassReplication.enabled -}}
true
{{- end -}}
{{- end }}

{{- define "vastextensionsmanager.vvr-validation-webhook-enabled" -}}
{{- if .Values.replication.webhooks.vastVolumeReplication.enabled -}}
true
{{- end -}}
{{- end }}

{{- define "vastextensionsmanager.vastExtensionControllerImage" -}}
{{- $images := .Values.image -}}
{{- $images.vastExtensionController.repository | default $images.vastExtensionController.defaultRepository -}}
{{- end }}

{{- define "vastextensionsmanager.csiAddonsControllerImage" -}}
{{- $images := .Values.image -}}
{{- $images.csiAddonsController.repository | default $images.csiAddonsController.defaultRepository -}}
{{- end }}
