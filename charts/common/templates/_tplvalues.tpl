{{/*
Render a string or YAML value through Helm tpl against the provided root context.
Usage: include "vast.common.tpl.render" (dict "root" $ "value" VALUE)
*/}}

{{- define "vast.common.tpl.render" -}}
{{- $value := .value -}}
{{- if kindIs "string" $value -}}
{{- tpl $value .root -}}
{{- else -}}
{{- tpl (toYaml $value) .root -}}
{{- end -}}
{{- end -}}
