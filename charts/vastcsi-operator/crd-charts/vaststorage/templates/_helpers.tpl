{{/* StorageClass/SnapshotClass helpers. Use vast.common.* for naming/labels/params. */}}

{{/*
Template: vastcsi.csiDriver
Resolves the correct CSI driver name based on the selected driver type.
- For Helm CLI installs, only `.Values.Provisioner` is expected.
- For OLM UI installs, `.Values.nfsProvisioner` and `.Values.blockProvisioner` may be provided and take precedence.
*/}}
{{- define "vastcsi.csiDriver" -}}
{{- if eq .Values.driverType "nfs" }}
  {{- coalesce .Values.nfsProvisioner .Values.provisioner | required "Driver Name is not provided" -}}
{{- else if eq .Values.driverType "block" }}
  {{- coalesce .Values.blockProvisioner .Values.provisioner | required "Driver Name is not provided" -}}
{{- else }}
  {{- fail (printf "Unsupported driver type: %s. Supported types are: nfs, cosi, csi, vastcsi." .Values.driverType) -}}
{{- end }}
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
csi.storage.k8s.io/node-expand-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/node-expand-secret-namespace: "{{ $secret_namespace }}"

{{- end -}}

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
