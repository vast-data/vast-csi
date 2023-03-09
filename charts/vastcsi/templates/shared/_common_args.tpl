{{- define "vastcsi.commonArgs" -}}
- "--csi-address=$(ADDRESS)"
- "--v={{ .Values.logLevel | default 5 }}"
{{- end }}
