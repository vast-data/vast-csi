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

{{/* Validate if vastCluster (underlying secret) exists. */}}
{{- define "vastcsi.vastCluster" -}}
{{- $secret := $.Values.clusterName -}}
{{- $secret_namespace := $.Release.Namespace -}}
{{- if not $secret -}}
  {{- fail "clusterName is empty" -}}
{{- end }}
{{- if $.Release.IsInstall -}}
{{- if not (lookup "v1" "Secret" $secret_namespace $secret) -}}
  {{- fail (printf "cluster '%s' doesn't exist in namespace '%s' or doesn't have underlying secret." .Values.clusterName .Release.Namespace) -}}
{{- end -}}
{{- end -}}
{{- $secret }}
{{- end -}}


{{/* Validate if secret exists. */}}
{{- define "vastcsi.secret" -}}
{{- $secret := $.Values.secretName -}}
{{- $secret_namespace := coalesce $.Values.secretNamespace $.Release.Namespace -}}
{{- if not $secret -}}
    {{- fail "secretName is empty" -}}
{{- end }}
{{- if $.Release.IsInstall -}}
{{- if not (lookup "v1" "Secret" $secret_namespace $secret) -}}
   {{- fail (printf "Secret '%s' not found in namespace '%s'." $secret $secret_namespace) -}}
{{- end -}}
{{- end -}}
{{- $secret }}
{{- end -}}


{{/*
Template: vastcsi.storageClassSecrets

Determines which Secret to use for CSI driver credentials.
If `.Values.secretName` is provided, it is used directly.
Otherwise, it falls back to `.Values.clusterName` and assumes a Secret with the same name exists.
*/}}
{{- define "vastcsi.storageClassSecrets" -}}

{{- $secret_name := .Values.secretName | trim -}}
{{- $cluster_name := .Values.clusterName | trim -}}

{{- if and (not $secret_name) (not $cluster_name) -}}
  {{- fail "Either 'secretName' or 'clusterName' must be provided." -}}
{{- end -}}

{{- $secret_namespace := "" -}}

{{- if $secret_name -}}
  {{- $secret_name = include "vastcsi.secret" $ | trim -}}
  {{- $secret_namespace = coalesce .Values.secretNamespace .Release.Namespace | trim -}}
{{- else -}}
  {{- $secret_name = include "vastcsi.vastCluster" $ | trim -}}
  {{- $secret_namespace = .Release.Namespace | trim -}}
{{- end -}}

csi.storage.k8s.io/provisioner-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/provisioner-secret-namespace: "{{ $secret_namespace }}"
csi.storage.k8s.io/controller-publish-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/controller-publish-secret-namespace: "{{ $secret_namespace }}"
csi.storage.k8s.io/node-publish-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/node-publish-secret-namespace: "{{ $secret_namespace }}"
csi.storage.k8s.io/node-stage-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/node-stage-secret-namespace: "{{ $secret_namespace }}"
csi.storage.k8s.io/controller-expand-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/controller-expand-secret-namespace: "{{ $secret_namespace }}"

{{- end -}}


{{/*
Template: vastcsi.snapshotClassSecrets

Generates CSI snapshot secret keys using either secretName or clusterName.
*/}}
{{- define "vastcsi.snapshotClassSecrets" -}}

{{- $secret_name := .Values.secretName | trim -}}
{{- $cluster_name := .Values.clusterName | trim -}}

{{- if and (not $secret_name) (not $cluster_name) -}}
  {{- fail "Either 'secretName' or 'clusterName' must be provided." -}}
{{- end -}}

{{- $secret_namespace := "" -}}

{{- if $secret_name -}}
  {{- $secret_name = include "vastcsi.secret" $ | trim -}}
  {{- $secret_namespace = coalesce .Values.secretNamespace .Release.Namespace | trim -}}
{{- else -}}
  {{- $secret_name = include "vastcsi.vastCluster" $ | trim -}}
  {{- $secret_namespace = .Release.Namespace | trim -}}
{{- end -}}

csi.storage.k8s.io/snapshotter-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/snapshotter-secret-namespace: "{{ $secret_namespace }}"

{{- end -}}
