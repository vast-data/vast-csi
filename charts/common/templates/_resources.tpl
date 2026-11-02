{{/*
Named resource factories. All require explicit dictionaries.
Application charts own feature gates and chart-specific policy.
*/}}

{{- define "vast.common.resource.csiDriver" -}}
{{- $volumeLifecycleModes := required "volumeLifecycleModes is required" .volumeLifecycleModes -}}
{{- if not (kindIs "slice" $volumeLifecycleModes) -}}
{{- fail "volumeLifecycleModes must be a list" -}}
{{- end -}}
{{- range $volumeLifecycleModes -}}
{{- if not (has . (list "Persistent" "Ephemeral")) -}}
{{- fail "volumeLifecycleModes entries must be Persistent or Ephemeral" -}}
{{- end -}}
{{- end -}}
{{- $podInfoOnMount := true -}}
{{- if hasKey . "podInfoOnMount" -}}
{{- $podInfoOnMount = .podInfoOnMount -}}
{{- end -}}
apiVersion: storage.k8s.io/v1
kind: CSIDriver
metadata:
  name: {{ .name }}
  labels:
{{ .labels | nindent 4 }}
spec:
  attachRequired: {{ .attachRequired }}
  podInfoOnMount: {{ $podInfoOnMount }}
{{- if hasKey . "seLinuxMount" }}
  seLinuxMount: {{ .seLinuxMount }}
{{- end }}
  volumeLifecycleModes:
{{ toYaml $volumeLifecycleModes | nindent 4 }}
{{- end -}}

{{- define "vast.common.resource.serviceAccount" -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  namespace: {{ .namespace }}
  labels:
{{ .labels | nindent 4 }}
{{- end -}}

{{- define "vast.common.resource.sslSecret" -}}
apiVersion: v1
kind: Secret
metadata:
  name: {{ .name }}
  namespace: {{ .namespace }}
  labels:
{{ .labels | nindent 4 }}
  annotations:
    checksum/vast-vms-authority-secret: {{ .certificate | sha256sum | trim }}
type: Opaque
data:
  ca-bundle.crt: |-
    {{ .certificate | b64enc }}
{{- end -}}

{{- define "vast.common.resource.metricsService" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
  namespace: {{ .namespace }}
  labels:
{{ .labels | nindent 4 }}
    app.kubernetes.io/component: metrics
    app.kubernetes.io/csi-role: {{ .role | quote }}
spec:
  type: ClusterIP
  clusterIP: None
  selector:
    app: {{ .appSelector }}
{{ .selectorLabels | nindent 4 }}
  ports:
    - name: metrics
      port: {{ .port }}
      targetPort: metrics
      protocol: TCP
{{- end -}}

{{- define "vast.common.resource.serviceMonitor" -}}
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: {{ .name }}
  namespace: {{ .namespace }}
  labels:
{{ .labels | nindent 4 }}
    app.kubernetes.io/component: metrics
    app.kubernetes.io/csi-role: {{ .role | quote }}
{{- with .additionalLabels }}
{{ toYaml . | nindent 4 }}
{{- end }}
spec:
  selector:
    matchLabels:
{{ .selectorLabels | nindent 6 }}
      app.kubernetes.io/component: metrics
      app.kubernetes.io/csi-role: {{ .role | quote }}
  namespaceSelector:
    matchNames:
      - {{ .namespace }}
  endpoints:
    - port: metrics
      interval: {{ .interval }}
      path: /metrics
      scheme: http
{{- with .relabelings }}
      relabelings:
{{ toYaml . | nindent 8 }}
{{- end }}
{{- with .metricRelabelings }}
      metricRelabelings:
{{ toYaml . | nindent 8 }}
{{- end }}
{{- end -}}

{{- define "vast.common.resource.webhookService" -}}
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
  namespace: {{ .namespace }}
  labels:
{{ .labels | nindent 4 }}
spec:
  ports:
    - port: 443
      targetPort: {{ .targetPort | default 9443 }}
      protocol: TCP
      name: webhook
  selector:
    app: {{ .appSelector }}
{{ .selectorLabels | nindent 4 }}
{{- end -}}

{{/*
Emit a kubernetes.io/tls Secret with a self-signed CA and leaf certificate.

Reuses an existing Secret on upgrade. Optionally fills .out with tlsCrt/tlsKey/caCrt
(base64) so callers can embed caBundle elsewhere in the same render.

Required: secretName, namespace, cn, altNames, caName, labels
Optional: days (validity in days; default 3650 / 10y), out (dict mutated with cert material)

Usage:
  {{ include "vast.common.resource.selfSignedCertificate" (dict
    "secretName" "my-service-tls"
    "namespace" "default"
    "cn" "my-service"
    "altNames" (list "my-service" "my-service.default.svc")
    "caName" "my-service-ca"
    "days" (include "vast.common.certs.defaultValidityDays" . | int)
    "labels" (include "vast.common.labels" .)
  ) }}
*/}}
{{- define "vast.common.resource.selfSignedCertificate" -}}
{{- $secretName := required "secretName is required" .secretName -}}
{{- $namespace := required "namespace is required" .namespace -}}
{{- $labels := required "labels is required" .labels -}}
{{/* Prefer caller-supplied out even when empty; `default` treats empty dict as empty. */}}
{{- $out := dict -}}
{{- if hasKey . "out" -}}
{{- $out = .out -}}
{{- end -}}
{{- $days := .days | default (include "vast.common.certs.defaultValidityDays" .) | int -}}
{{- include "vast.common.certs.generate" (dict
  "out" $out
  "secretName" $secretName
  "namespace" $namespace
  "cn" .cn
  "altNames" .altNames
  "caName" .caName
  "days" $days
) }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ $secretName }}
  namespace: {{ $namespace }}
  labels:
{{ $labels | nindent 4 }}
type: kubernetes.io/tls
data:
  tls.crt: {{ $out.tlsCrt }}
  tls.key: {{ $out.tlsKey }}
  ca.crt:  {{ $out.caCrt }}
{{- end -}}

{{- define "vast.common.resource.webhookCertificate" -}}
{{- $name := required "webhook certificate name is required" .name -}}
{{- $namespace := required "webhook certificate namespace is required" .namespace -}}
{{- $secretName := printf "%s-tls" $name -}}
{{- $cn := printf "%s.%s.svc" $name $namespace -}}
{{- $altNames := list $cn (printf "%s.%s.svc.cluster.local" $name $namespace) -}}
{{- $certs := dict -}}
{{- $days := .days | default (include "vast.common.certs.defaultValidityDays" .) | int -}}
{{- include "vast.common.resource.selfSignedCertificate" (dict
  "secretName" $secretName
  "namespace" $namespace
  "cn" $cn
  "altNames" $altNames
  "caName" (.caName | default "vast-webhook-ca")
  "days" $days
  "labels" .labels
  "out" $certs
) }}
---
apiVersion: admissionregistration.k8s.io/v1
kind: {{ .configurationKind | default "MutatingWebhookConfiguration" }}
metadata:
  name: {{ $name }}
  labels:
{{ .labels | nindent 4 }}
webhooks:
{{- range .webhooks }}
  - name: {{ .name }}
    admissionReviewVersions: ["v1"]
    sideEffects: None
    failurePolicy: {{ .failurePolicy | default "Fail" }}
{{- if .timeoutSeconds }}
    timeoutSeconds: {{ .timeoutSeconds }}
{{- end }}
    clientConfig:
      service:
        name: {{ $name }}
        namespace: {{ $namespace }}
        path: {{ .path }}
      caBundle: {{ $certs.caCrt }}
    rules:
{{ toYaml .rules | nindent 6 }}
{{- with .namespaceSelector }}
    namespaceSelector:
{{ toYaml . | nindent 6 }}
{{- end }}
{{- end }}
{{- end -}}
