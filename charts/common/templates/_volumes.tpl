{{/*
Shared volume and volume-mount fragments for auth, credential serialization, and
optional NFS service TLS assets. Inputs use the chart root context. Templates that emit
lists return a leading newline only when they produce content, so call sites can be
written as `{{- include "..." . | indent N }}` right after a list item without leaving
a blank line behind when nothing is mounted.
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

{{/*
True when node.nfsServices.tlshd ConfigMap and certificates.secretName are both set.
*/}}
{{- define "vast.common.nfsServices.tlshdOverridesEnabled" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if and $tlshd.configMap ($certs.secretName | default "") -}}
true
{{- end -}}
{{- end -}}

{{/*
TLS / tlshd sidecar volumes for csi-nfs-services.
ConfigMap (tlshd.conf) and Secret (PEM files) must live in the node pod namespace.
*/}}
{{- define "vast.common.nfsServices.tlshdVolumeMounts" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if $tlshd.configMap }}
- name: tlshd-conf
  mountPath: /etc/tlshd.conf
  subPath: tlshd.conf
  readOnly: true
{{- else }}
- name: tlshd-conf
  mountPath: /etc/tlshd.conf
  readOnly: true
{{- end }}
{{- if $certs.secretName }}
- name: tlshd-certs
  mountPath: {{ $certs.mountPath | default "/etc/vast-tlshd" }}
  readOnly: true
{{- end }}
{{- end -}}

{{- define "vast.common.nfsServices.tlshdVolumes" -}}
{{- $tlshd := .Values.node.nfsServices.tlshd | default dict -}}
{{- $certs := $tlshd.certificates | default dict -}}
{{- if and $tlshd.configMap (not $certs.secretName) }}
{{- fail "node.nfsServices.tlshd: certificates.secretName is required when configMap is set" }}
{{- end }}
{{- if and ($certs.secretName) (not $tlshd.configMap) }}
{{- fail "node.nfsServices.tlshd: configMap is required when certificates.secretName is set" }}
{{- end }}
{{- if $tlshd.configMap }}
- name: tlshd-conf
  configMap:
    name: {{ $tlshd.configMap }}
    defaultMode: 0444
{{- else }}
- name: tlshd-conf
  hostPath:
    path: /etc/tlshd.conf
    type: File
{{- end }}
{{- if $certs.secretName }}
- name: tlshd-certs
  secret:
    secretName: {{ $certs.secretName }}
    defaultMode: 0444
{{- end }}
{{- end -}}
