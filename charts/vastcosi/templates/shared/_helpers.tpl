{{/*
Serializes a dict/map or array/list to a JSON string parameter.
Usage: include "vastcsi.dictToJsonStringParam" (list $value "param_name")
*/}}
{{- define "vastcsi.dictToJsonStringParam" -}}
{{- $value := index . 0 -}}
{{- $key := index . 1 -}}
{{- if or (kindIs "map" $value) (kindIs "slice" $value) }}
{{ $key }}: {{ $value | toJson | quote }}
{{- else }}
  {{- $errorMsg := printf "Invalid format. Expected a map or array for JSON serialization but got:\n%s" (toYaml $value) }}
  {{- fail $errorMsg }}
{{- end }}
{{- end }}
