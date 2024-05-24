{{- define "vastcosinamespace" -}}
{{- coalesce $.Release.Namespace "vast-csi" | quote -}}
{{- end }}
