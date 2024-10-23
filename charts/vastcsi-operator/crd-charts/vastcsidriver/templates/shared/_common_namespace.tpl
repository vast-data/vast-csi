{{- define "vastcsi.namespace" -}}
{{- quote (coalesce $.Release.Namespace "vast-csi") -}}
{{- end }}
