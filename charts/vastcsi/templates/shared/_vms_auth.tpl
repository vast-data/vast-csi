{{/*Set of templates for working with vms credentials and vms session certificates*/}}

{{/*Unique checksum based on provided username and password.*/}}
{{- define "vastcsi.credentialsChecksum" -}}
{{- cat .Values.username  .Values.password | sha256sum -}}
{{- end }}


{{/*Unique checksum based on provided sslCert. Generate empty checksum if sslCert are not provided.*/}}
{{- define "vastcsi.sslChecksum" -}}
{{- if .Values.sslCert -}}
{{- .Values.sslCert | sha256sum -}}
{{- else -}}
""
{{ end }}
{{- end }}


{{/*
Projected volume based on `csi-vast-mgmt` and `csi-vast-vms-authority` secrets
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
        name: csi-vast-mgmt
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
Volume mount based on `csi-vast-mgmt` and `csi-vast-vms-authority` secrets
Expected files within volume:
 - sslCert:  root certificate authority
 - username: vms session username
 - password: vms session password
*/}}
{{ define "vastcsi.vmsAuthVolumeMount" }}
- name: vms-auth
  mountPath: /opt/vms-auth
{{- end }}
