{{/*
Self-signed TLS certificate helpers.

Generate CA+leaf material once (or reuse an existing Secret on upgrade), then emit a
kubernetes.io/tls Secret or feed caBundle into admission configs.
*/}}

{{/*
Default cert validity: 10 years (Helm genCA / genSignedCert take days).
*/}}
{{- define "vast.common.certs.defaultValidityDays" -}}
3650
{{- end -}}

{{/*
Populate .out with base64-encoded tlsCrt, tlsKey, and caCrt.

Reuses an existing Secret when present so upgrades do not rotate the cert. Otherwise
generates a new CA and leaf via Helm's genCA / genSignedCert.

Required: out, secretName, namespace, cn, altNames, caName
Optional: days (validity in days; default vast.common.certs.defaultValidityDays = 3650 / 10y)

Usage:
  {{- $certs := dict }}
  {{- include "vast.common.certs.generate" (dict
    "out" $certs
    "secretName" "my-service-tls"
    "namespace" "default"
    "cn" "my-service"
    "altNames" (list "my-service" "my-service.default.svc")
    "caName" "my-service-ca"
    "days" (include "vast.common.certs.defaultValidityDays" . | int)
  ) }}
  {{/* $certs.tlsCrt $certs.tlsKey $certs.caCrt */}}
*/}}
{{- define "vast.common.certs.generate" -}}
{{- $out := required "out is required" .out -}}
{{- $secretName := required "secretName is required" .secretName -}}
{{- $namespace := required "namespace is required" .namespace -}}
{{- $cn := required "cn is required" .cn -}}
{{- $altNames := required "altNames is required" .altNames -}}
{{- if not (kindIs "slice" $altNames) -}}
{{- fail "altNames must be a list" -}}
{{- end -}}
{{- $caName := required "caName is required" .caName -}}
{{- $days := .days | default (include "vast.common.certs.defaultValidityDays" .) | int -}}
{{- $existingSecret := lookup "v1" "Secret" $namespace $secretName -}}
{{- if $existingSecret -}}
  {{- $_ := set $out "tlsCrt" (index $existingSecret.data "tls.crt") -}}
  {{- $_ := set $out "tlsKey" (index $existingSecret.data "tls.key") -}}
  {{- $_ := set $out "caCrt" (index $existingSecret.data "ca.crt") -}}
{{- else -}}
  {{- $ca := genCA $caName $days -}}
  {{- $cert := genSignedCert $cn nil $altNames $days $ca -}}
  {{- $_ := set $out "tlsCrt" ($cert.Cert | b64enc) -}}
  {{- $_ := set $out "tlsKey" ($cert.Key | b64enc) -}}
  {{- $_ := set $out "caCrt" ($ca.Cert | b64enc) -}}
{{- end -}}
{{- end -}}
