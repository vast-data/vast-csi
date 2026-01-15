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
{{- if $.Values.truncateVolumeName }}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
- name: X_CSI_BLOCK_HOSTS_AUTO_PRUNE
  value: {{ $.Values.blockHostsAutoPrune | quote }}
{{- end }}

{{- end }}
