{{/*
Named resource factories. All require explicit dictionaries.
Application charts own feature gates and chart-specific policy.
*/}}

{{- define "vast.common.resource.csiDriver" -}}
apiVersion: storage.k8s.io/v1
kind: CSIDriver
metadata:
  name: {{ .name }}
  labels:
{{ .labels | nindent 4 }}
spec:
  attachRequired: {{ .attachRequired }}
  podInfoOnMount: {{ .podInfoOnMount | default true }}
  volumeLifecycleModes:
{{ toYaml .volumeLifecycleModes | nindent 4 }}
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

{{- define "vast.common.resource.webhookCertificate" -}}
{{- $name := required "webhook certificate name is required" .name -}}
{{- $namespace := required "webhook certificate namespace is required" .namespace -}}
{{- $days := .days | default 3650 -}}
{{- $secretName := printf "%s-tls" $name -}}
{{- $cn := printf "%s.%s.svc" $name $namespace -}}
{{- $altNames := list $cn (printf "%s.%s.svc.cluster.local" $name $namespace) -}}
{{- $existingSecret := lookup "v1" "Secret" $namespace $secretName -}}
{{- $tlsCrt := "" -}}
{{- $tlsKey := "" -}}
{{- $caCrt := "" -}}
{{- if $existingSecret -}}
  {{- $tlsCrt = index $existingSecret.data "tls.crt" -}}
  {{- $tlsKey = index $existingSecret.data "tls.key" -}}
  {{- $caCrt = index $existingSecret.data "ca.crt" -}}
{{- else -}}
  {{- $ca := genCA (.caName | default "vast-webhook-ca") $days -}}
  {{- $cert := genSignedCert $cn nil $altNames $days $ca -}}
  {{- $tlsCrt = $cert.Cert | b64enc -}}
  {{- $tlsKey = $cert.Key | b64enc -}}
  {{- $caCrt = $ca.Cert | b64enc -}}
{{- end }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ $secretName }}
  namespace: {{ $namespace }}
  labels:
{{ .labels | nindent 4 }}
type: kubernetes.io/tls
data:
  tls.crt: {{ $tlsCrt }}
  tls.key: {{ $tlsKey }}
  ca.crt:  {{ $caCrt }}
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
      caBundle: {{ $caCrt }}
    rules:
{{ toYaml .rules | nindent 6 }}
{{- with .namespaceSelector }}
    namespaceSelector:
{{ toYaml . | nindent 6 }}
{{- end }}
{{- end }}
{{- end -}}
