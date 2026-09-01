{{/*
Image helpers.
*/}}

{{/*
Render a required repository:tag image reference.
Usage: include "vast.common.image" (dict "root" $ "image" .Values.image.csiProvisioner)
*/}}
{{- define "vast.common.image" -}}
{{- $image := required "image is required" .image -}}
{{- $repository := include "vast.common.tpl.render" (dict "root" .root "value" ($image.repository | default "")) -}}
{{- $tag := include "vast.common.tpl.render" (dict "root" .root "value" ($image.tag | default "")) -}}
{{- printf "%s:%s"
  (required "image repository is required" $repository)
  (required "image tag is required" $tag)
-}}
{{- end -}}

{{/* Image pull secret fragment. Usage: include "vast.common.imagePullSecrets" (dict "secrets" LIST) */}}
{{- define "vast.common.imagePullSecrets" -}}
{{- with .secrets }}
imagePullSecrets:
{{ toYaml . | indent 2 }}
{{- end }}
{{- end -}}
