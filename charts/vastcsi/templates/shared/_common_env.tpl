{{- define "vastcsi.commonEnv" -}}
{{- $vast_config := .Files.Get "vast-config.yaml" | fromYaml -}}

{{- if not $.Values.deletionVipPool -}}
  {{- fail "deletionVipPool is required value. Please specify valid deletion vip pool" -}}
{{- end }}

{{- if (urlParse (required "endpoint is required" $.Values.endpoint )).scheme }}
    {{- fail "endpoint requires only host to be provided. Please exclude 'http//|https//' from url." -}}
{{- end  -}}
{{- with $fist_storage_class := values .Values.storageClasses | first }}
- name: X_CSI_PLUGIN_NAME
  value: "csi.vastdata.com"
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | quote }}
- name: X_CSI_DISABLE_VMS_SSL_VERIFICATION
  value: {{ $.Values.verifySsl | quote }}
- name: X_CSI_DELETION_VIP_POOL_NAME
  value: {{ $.Values.deletionVipPool | quote }}
- name: X_CSI_VMS_USER
  valueFrom:
    secretKeyRef:
      name: csi-vast-mgmt
      key: username
- name: X_CSI_VMS_PASSWORD
  valueFrom:
    secretKeyRef:
      name: csi-vast-mgmt
      key: password
{{- end }}
{{- end }}
