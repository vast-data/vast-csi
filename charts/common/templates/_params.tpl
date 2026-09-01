{{/*
Parameter serializers for StorageClass / SnapshotClass / BucketClass maps.
*/}}

{{- define "vast.common.params.keyValue" -}}
{{- range $key, $value := .values }}
  {{- if and $value (ne $value (quote "")) }}
{{ $key }}: {{ if kindIs "int" $value }}{{ $value | quote }}{{ else }}{{ $value }}{{ end }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "vast.common.params.bool" -}}
{{- range $key, $value := .values }}
  {{- if kindIs "bool" $value }}
    {{- if $value }}
{{ $key }}: "true"
    {{- else }}
{{ $key }}: "false"
    {{- end }}
  {{- else }}
    {{- $normalized := trimAll "\"" (toString $value) | lower }}
    {{- if or (eq $normalized "true") (eq $normalized "1") (eq $normalized "on") }}
{{ $key }}: "true"
    {{- else if or (eq $normalized "false") (eq $normalized "0") (eq $normalized "off") }}
{{ $key }}: "false"
    {{- end }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "vast.common.params.json" -}}
{{- if or (kindIs "map" .value) (kindIs "slice" .value) }}
{{ .key }}: {{ .value | toJson | quote }}
{{- else }}
{{- fail (printf "Invalid format. Expected a map or array for JSON serialization but got:\n%s" (toYaml .value)) }}
{{- end }}
{{- end -}}
