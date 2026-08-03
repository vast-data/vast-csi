{{/*
Renders key-value pairs for COSI parameters.
- Quotes all values except ints.
- Skips empty values.

Usage: include "vastcosi.dictToKeyValParams" (list (dict ...))
*/}}
{{- define "vastcosi.dictToKeyValParams" -}}
{{- $input := index . 0 -}}
  {{- range $key, $value := $input }}
    {{- if and $value (ne $value (quote "")) }}
{{ $key }}: {{ if kindIs "int" $value }}{{ $value | quote }}{{ else }}{{ $value }}{{ end }}
    {{- end }}
  {{- end }}
{{- end }}


{{/*
Renders key-value pairs where the value is interpreted as boolean true.
Truthy values include:
- bool true
- strings: "true", "1", "on" (case-insensitive, trims quotes)

Result: key: "true"
*/}}
{{- define "vastcosi.dictToBoolParams" -}}
{{- $input := index . 0 -}}
{{- range $key, $value := $input }}
  {{- if kindIs "bool" $value }}
    {{- if $value }}
{{ $key }}: "true"
    {{- end }}
  {{- else }}
    {{- $normalized := trimAll "\"" (toString $value) | lower }}
    {{- if or (eq $normalized "true") (eq $normalized "1") (eq $normalized "on") }}
{{ $key }}: "true"
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}


{{/*
Serializes a dict/map or array/list to a JSON string parameter.
Usage: include "vastcosi.dictToJsonStringParam" (list $value "param_name")
*/}}
{{- define "vastcosi.dictToJsonStringParam" -}}
{{- $value := index . 0 -}}
{{- $key := index . 1 -}}
{{- if or (kindIs "map" $value) (kindIs "slice" $value) }}
{{ $key }}: {{ $value | toJson | quote }}
{{- else }}
  {{- $errorMsg := printf "Invalid format. Expected a map or array for JSON serialization but got:\n%s" (toYaml $value) }}
  {{- fail $errorMsg }}
{{- end }}
{{- end }}
