{{/*Set of templates for working with vms credentials and vms session certificates*/}}

{{/* Volume declarations for vms credentials and vms session certificates */}}
{{- define "vastcosivmsAuthVolume" -}}
{{- if and .Values.sslCert .Values.sslCertsSecretName -}}
{{-
    fail (printf "Ambiguous origin of the 'sslCert'. The certificate is found in both the '%s' secret and the command line --from-file argument." .Values.secretName)
-}}
{{- end -}}
{{- if and .ca_bundle (not .Values.verifySsl) -}}
  {{- fail "When sslCert is provided `verifySsl` must be set to true." -}}
{{- end }}

- name: vms-auth
  secret:
    secretName: {{ required "secretName field must be specified" .Values.secretName | quote }}
    items:
    - key: username
      path: username
    - key: password
      path: password
{{- if $.ca_bundle }}
- name: vms-ca-bundle
  secret:
    secretName: {{ $.ca_bundle }}
    items:
    - key: ca-bundle.crt
      path: ca-certificates.crt
{{- end }}
{{- end }}


{{/* Volume bindings for vms credentials and vms session certificates */}}
{{ define "vastcosivmsAuthVolumeMount" }}
- name: vms-auth
  mountPath: /opt/vms-auth
  readOnly: true
{{- if $.ca_bundle }}
- name: vms-ca-bundle
  mountPath: /etc/ssl/certs
  readOnly: true
{{- end }}
{{- end }}
