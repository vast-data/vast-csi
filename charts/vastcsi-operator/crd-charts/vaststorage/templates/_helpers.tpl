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
csi.storage.k8s.io/node-expand-secret-name: "{{ $secret_name }}"
csi.storage.k8s.io/node-expand-secret-namespace: "{{ $secret_namespace }}"

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


{{/*
Renders key-value pairs for CSI parameters.
- Quotes all values except ints.
- Skips empty values.

Usage: include "vastcsi.dictToKeyValParams" (dict $your_dict)
*/}}
{{- define "vastcsi.dictToKeyValParams" -}}
{{- $input := index . 0 -}}
  {{- range $key, $value := $input }}
    {{- if and $value (ne $value (quote "")) }}
{{ $key }}: {{ if kindIs "int" $value }}{{ $value | quote }}{{ else }}{{ $value }}{{ end }}
    {{- end }}
  {{- end }}
{{- end }}


{{/*
Renders key-value pairs where the value is interpreted as boolean true.
Truthy values include:
- bool true
- strings: "true", "1", "on" (case-insensitive, trims quotes)

Result: key: "true"
*/}}
{{- define "vastcsi.dictToBoolParams" -}}
{{- $input := index . 0 -}}
{{- range $key, $value := $input }}
  {{- if kindIs "bool" $value }}
    {{- if $value }}
{{ $key }}: "true"
    {{- end }}
  {{- else }}
    {{- $normalized := trimAll "\"" (toString $value) | lower }}
    {{- if or (eq $normalized "true") (eq $normalized "1") (eq $normalized "on") }}
{{ $key }}: "true"
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}


{{/*
Renders a key-value pair where the value is the input map serialized to a JSON string.

Inputs:
- .0: map to serialize (must be of type "map")
- .1: key to associate with the JSON string

Result:
<key>: "<JSON-string>"

Fails if the input is not a map.
*/}}
{{- define "vastcsi.dictToJsonStringParam" -}}
{{- $map := index . 0 -}}
{{- $key := index . 1 -}}
{{- if not (kindIs "map" $map) }}
  {{- $errorMsg := printf "Invalid format. Expected a map for JSON serialization but got:\n%s" (toYaml $map) }}
  {{- fail $errorMsg }}
{{- else }}
{{ $key }}: {{ $map | toJson | quote }}
{{- end }}
{{- end }}

