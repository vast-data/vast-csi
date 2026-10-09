{{/* OLM/operator-specific helpers only. Use vast.common.* directly in templates. */}}

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

{{- define "vastextensionsmanager.grpcTLSSecretName" -}}
{{- printf "%s-tls" (include "vastextensionsmanager.grpcServiceName" .) -}}
{{- end }}

{{- define "vastextensionsmanager.grpcCertificateName" -}}
{{- $default := printf "%s-cert" (include "vastextensionsmanager.grpcServiceName" .) -}}
{{- default $default .Values.grpc.certManager.certificateRef.name -}}
{{- end }}

{{- define "vastextensionsmanager.webhookTLSSecretName" -}}
{{- printf "%s-tls" (include "vastextensionsmanager.webhookServiceName" .) -}}
{{- end }}

{{- define "vastextensionsmanager.webhookCertificateName" -}}
{{- $default := printf "%s-cert" (include "vastextensionsmanager.webhookServiceName" .) -}}
{{- default $default .Values.webhook.certManager.certificateRef.name -}}
{{- end }}

{{- define "vastextensionsmanager.webhookInjectCAFrom" -}}
{{- $ns := default (include "vast.common.namespace" . | trimAll "\"") .Values.webhook.certManager.certificateRef.namespace -}}
{{- printf "%s/%s" $ns (include "vastextensionsmanager.webhookCertificateName" .) -}}
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

{{- define "vastextensionsmanager.resolvedImage" -}}
{{- $img := .img -}}
{{- if .ctx.Values.image.useCustomRepositories -}}
{{- coalesce $img.repository $img.defaultRepository -}}
{{- else -}}
{{- coalesce $img.defaultRepository $img.repository -}}
{{- end -}}
{{- end }}

{{- define "vastextensionsmanager.vastExtensionControllerImage" -}}
{{- include "vastextensionsmanager.resolvedImage" (dict "ctx" . "img" .Values.image.vastExtensionController) -}}
{{- end }}

{{- define "vastextensionsmanager.csiAddonsControllerImage" -}}
{{- include "vastextensionsmanager.resolvedImage" (dict "ctx" . "img" .Values.image.csiAddonsController) -}}
{{- end }}
