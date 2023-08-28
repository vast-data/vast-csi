{{/*Set of templates for working with vms credentials and vms session certificates*/}}

{{/*Unique checksum based on provided sslCert. Generate empty checksum if sslCert are not provided.*/}}
{{- define "vastcsi.sslChecksum" -}}
{{- if .Values.sslCert -}}
{{- .Values.sslCert | sha256sum -}}
{{- else -}}
""
{{ end }}
{{- end }}

{{/*
Projected volume based on mgmt secret provided by user and `csi-vast-vms-authority` secret
Expected files within volume:
 - sslCert:  root certificate authority
 - username: vms session username
 - password: vms session password
*/}}

{{- define "vastcsi.vmsAuthVolume" -}}
{{- $ssl_checksum := printf "%s" (include "vastcsi.sslChecksum" .) | trim }}
- name: vms-auth
  projected:
    defaultMode: 0400
    sources:
    - secret:
        name: {{ required "secretName field must be specified" $.Values.secretName | quote }}
        items:
        - key: username
          path: username
        - key: password
          path: password
    {{- if ne $ssl_checksum ( quote "" ) }}
    - secret:
        name: csi-vast-vms-authority
        items:
        - key: sslCert
          path: sslCert
    {{- end }}
{{- end }}


{{/*
Volume mount based on mgmt secret provided by user and `csi-vast-vms-authority` secret
Expected files within volume:
 - sslCert:  root certificate authority
 - username: vms session username
 - password: vms session password
*/}}

{{ define "vastcsi.vmsAuthVolumeMount" }}
- name: vms-auth
  mountPath: /opt/vms-auth
{{- end }}
