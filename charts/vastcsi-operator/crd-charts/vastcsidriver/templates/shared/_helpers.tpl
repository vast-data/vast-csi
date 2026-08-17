{{- /*
# IMPORTANT: cosi and csi helm charts share similar templates.
# If you make changes to a template in one chart, make sure to replicate those
# changes in the corresponding template in the other chart.
*/}}

{{- define "vastcsi.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastcsi.commonArgs" -}}
- "--csi-address=$(ADDRESS)"
- "--v={{ .Values.logLevel | default 5 }}"
{{- end }}

{{- define "vastcsi.namespace" -}}
{{- quote (coalesce $.Release.Namespace "vast-csi") -}}
{{- end }}

{{- define "vastcsi.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "vastcsi.dnsSafeReleaseName" -}}
{{- .Release.Name | replace "." "-" | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "vastcsi.workloadNamePrefix" -}}
{{- ternary "csi" "block" (eq .Values.driverType "nfs") -}}
{{- end }}

{{- define "vastcsi.extensionControllerName" -}}
{{- printf "%s-vast-extension-controller" (include "vastcsi.workloadNamePrefix" .) -}}
{{- end }}

{{- define "vastcsi.webhookServiceName" -}}
{{- printf "%s-vast-extension-controller-webhook" (include "vastcsi.dnsSafeReleaseName" .) -}}
{{- end }}

{{- define "vastcsi.webhookTLSSecretName" -}}
{{- printf "%s-tls" (include "vastcsi.webhookServiceName" .) -}}
{{- end }}

{{- define "vastcsi.webhookCertificateName" -}}
{{- $default := printf "%s-cert" (include "vastcsi.webhookServiceName" .) -}}
{{- default $default .Values.extensions.webhook.certManager.certificateRef.name -}}
{{- end }}

{{- define "vastcsi.webhookInjectCAFrom" -}}
{{- $ns := default (include "vastcsi.namespace" . | trimAll "\"") .Values.extensions.webhook.certManager.certificateRef.namespace -}}
{{- printf "%s/%s" $ns (include "vastcsi.webhookCertificateName" .) -}}
{{- end }}

{{/*
Normalize node.nfsServices.services for Helm and OLM UI.
The console may store a single array element like "statd rpcbind" instead of ["statd", "rpcbind"].
*/}}
{{- define "vastcsi.nfsServicesArg" -}}
{{- join "," (compact (splitList " " (join " " (default list .Values.node.nfsServices.services)))) -}}
{{- end -}}

{{/* Common labels */}}
{{- define "vastcsi.labels" -}}
helm.sh/chart: {{ include "vastcsi.chart" . }}
{{ include "vastcsi.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
storage.vastdata.com/driverType: {{ .Values.driverType }}
{{- end }}

{{/* Common selectors */}}
{{- define "vastcsi.selectorLabels" -}}
app.kubernetes.io/name: {{ include "vastcsi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "vastcsi.csiDriver" -}}
{{- $default_driver_name := ternary "csi.vastdata.com" "block.csi.vastdata.com" (eq $.Values.driverType "nfs") -}}
{{- coalesce .Release.Name $default_driver_name -}}
{{- end -}}

{{- define "vastcsi.commonEnv" }}
- name: X_CSI_PLUGIN_NAME
  value: {{ include "vastcsi.csiDriver" $ | quote }}
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | default "" | quote }}
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
- name: X_CSI_DISABLE_USAGE_STATS
  value: {{ $.Values.disableUsageStats | default false | quote }}
- name: X_CSI_CACHE_MAX_AGE
  value: {{ $.Values.cacheMaxAgeSeconds | default 0 | quote }}
- name: X_CSI_MOUNT_UMOUNT_TIMEOUT
  value: {{ $.Values.mountUmountTimeout | quote }}
- name: X_CSI_FORCE_LAZY_UMOUNT_ON_TIMEOUT
  value: {{ $.Values.forceLazyUmountOnTimeout | quote }}
{{- if $.Values.resolveMountSymlinks }}
- name: X_CSI_RESOLVE_MOUNT_SYMLINKS
  value: {{ $.Values.resolveMountSymlinks | quote }}
{{- end }}
{{- if $.Values.allowROManyBlockFsMode }}
- name: X_CSI_ALLOW_RO_MANY_BLOCK_FS_MODE
  value: {{ $.Values.allowROManyBlockFsMode | quote }}
{{- end }}
{{- if $.Values.truncateVolumeName }}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
{{- end }}
- name: X_CSI_BLOCK_HOSTS_AUTO_PRUNE
  value: {{ $.Values.blockHostsAutoPrune | quote }}
{{- if $.Values.hostNamePrefix }}
- name: X_CSI_HOST_NAME_PREFIX
  value: {{ $.Values.hostNamePrefix | quote }}
{{- end }}

{{- end }}


{{/*
Return true if the extension controller feature is enabled.
The extension controller (and all associated resources — CRDs, RBAC, service account) is
activated exclusively by extensions.enabled.  Sub-flags such as
extensions.webhook.disablePvcLabelsWebhook are forwarded as CLI arguments to the running
process and do NOT affect whether resources are created.
Usage:
{{- include "vastcsi.extension-enabled" . -}}
*/}}
{{- define "vastcsi.extension-enabled" -}}
{{- if .Values.extensions.enabled -}}
{{- true -}}
{{- end -}}
{{- end -}}

{{/*
Return true when the replication stack is enabled.
*/}}
{{- define "vastcsi.replication-enabled" -}}
{{- if and .Values.extensions.enabled .Values.extensions.replication.enabled -}}
{{- true -}}
{{- end -}}
{{- end -}}


{{- define "vastcsi.vastExtensionControllerImage" -}}
{{- $images := .Values.image -}}
{{- $images.vastExtensionController.repository | default $images.vastExtensionController.defaultRepository -}}
{{- end -}}


{{/*
Build the comma-separated list of addons to enable.
VolumeGroupReplicationClass is always created alongside VolumeReplicationClass.
Usage:
{{- include "vastcsi.addons-list" (dict "root" . "type" "nfs") -}}
*/}}
{{- define "vastcsi.addons-list" -}}
{{- $type := .type -}}
{{- join "," (list (printf "replication[%s]" $type) (printf "volumegroup[%s]" $type)) -}}
{{- end -}}

{{- define "vastcsi.fallbackToDeserEnv" -}}
{{- if not (kindIs "bool" .Values.fallbackToDeser) }}
{{- fail "fallbackToDeser must be set explicitly to true or false" }}
{{- end }}
- name: X_CSI_FALLBACK_TO_DESER
  value: {{ .Values.fallbackToDeser | quote }}
{{- end }}
