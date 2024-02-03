{{- /*
# IMPORTANT: cosi and csi helm charts share similar templates.
# If you make changes to a template in one chart, make sure to replicate those
# changes in the corresponding template in the other chart.
*/}}

{{- define "vastcosicommonEnv" -}}

{{- if (urlParse (required "endpoint is required" $.Values.endpoint )).scheme }}
    {{- fail "endpoint requires only host to be provided. Please exclude 'http//|https//' from url." -}}
{{- end  }}
- name: X_CSI_PLUGIN_NAME
  value: "csi.vastdata.com"
- name: X_CSI_VMS_HOST
  value: {{ $.Values.endpoint | quote }}
- name: X_CSI_ENABLE_VMS_SSL_VERIFICATION
  value: {{ $.Values.verifySsl | quote }}
- name: X_CSI_WORKER_THREADS
  value: {{ $.Values.numWorkers | quote }}
{{ if $.Values.truncateVolumeName -}}
- name: X_CSI_TRUNCATE_VOLUME_NAME
  value: {{ $.Values.truncateVolumeName | quote }}
{{- end }}
{{- end }}
