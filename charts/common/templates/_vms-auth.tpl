{{/*
VMS auth and credential-serialization volume fragments.
Input is the chart root context. Every template emits a leading newline only when it has
content, so call sites can be written as `{{- include "..." . | indent N }}` right after a
list item without leaving a blank line behind when nothing is mounted.
*/}}

{{/* Secret holding the CA bundle: the built-in one when a cert is passed on the command line, the user secret otherwise. */}}
{{- define "vast.common.vmsAuth.caBundle" -}}
{{- empty .Values.sslCert | ternary .Values.sslCertsSecretName "csi-vast-ca-bundle" -}}
{{- end -}}

{{- define "vast.common.vmsAuth.volumes" -}}
{{- $rendered := include "vast.common.vmsAuth.volumesBody" . -}}
{{- if $rendered }}{{ printf "\n%s" $rendered }}{{- end }}
{{- end -}}

{{- define "vast.common.vmsAuth.volumesBody" -}}
{{- $caBundle := include "vast.common.vmsAuth.caBundle" . -}}
{{- if and .Values.sslCert .Values.sslCertsSecretName }}
{{- fail (printf "Ambiguous origin of the 'sslCert'. The certificate is found in both the '%s' secret and the command line --from-file argument." .Values.sslCertsSecretName) }}
{{- end }}
{{- if and $caBundle (not .Values.verifySsl) }}
{{- fail "When sslCert is provided `verifySsl` must be set to true." }}
{{- end }}
{{- if .Values.secretName }}
- name: vms-auth
  secret:
    secretName: {{ .Values.secretName | quote }}
{{- end }}
{{- if $caBundle }}
- name: vms-ca-bundle
  secret:
    secretName: {{ $caBundle }}
    items:
    - key: ca-bundle.crt
      path: ca-certificates.crt
{{- end }}
{{- end -}}

{{- define "vast.common.vmsAuth.volumeMounts" -}}
{{- $rendered := include "vast.common.vmsAuth.volumeMountsBody" . -}}
{{- if $rendered }}{{ printf "\n%s" $rendered }}{{- end }}
{{- end -}}

{{- define "vast.common.vmsAuth.volumeMountsBody" -}}
{{- $caBundle := include "vast.common.vmsAuth.caBundle" . -}}
{{- if .Values.secretName }}
- name: vms-auth
  mountPath: /opt/vms-auth
  readOnly: true
{{- end }}
{{- if $caBundle }}
- name: vms-ca-bundle
  mountPath: /etc/ssl/certs
  readOnly: true
{{- end }}
{{- end -}}

{{- define "vast.common.credSerde.volume" -}}
{{- $rendered := include "vast.common.credSerde.volumeBody" . -}}
{{- if $rendered }}{{ printf "\n%s" $rendered }}{{- end }}
{{- end -}}

{{- define "vast.common.credSerde.volumeBody" -}}
{{- if .Values.credSerializationSecret }}
- name: cred-serde
  secret:
    secretName: {{ .Values.credSerializationSecret | quote }}
    items:
    - key: key
      path: key
{{- end }}
{{- end -}}

{{- define "vast.common.credSerde.volumeMount" -}}
{{- $rendered := include "vast.common.credSerde.volumeMountBody" . -}}
{{- if $rendered }}{{ printf "\n%s" $rendered }}{{- end }}
{{- end -}}

{{- define "vast.common.credSerde.volumeMountBody" -}}
{{- if .Values.credSerializationSecret }}
- name: cred-serde
  mountPath: /opt/cred-serde
  readOnly: true
{{- end }}
{{- end -}}
