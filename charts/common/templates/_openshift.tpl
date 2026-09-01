{{/*
OpenShift detection helpers.
*/}}

{{/*
Return true when the target cluster is OpenShift.

Usage: include "vast.common.openshift.isOpenshift" .
*/}}
{{- define "vast.common.openshift.isOpenshift" -}}
{{- if .Capabilities.APIVersions.Has "security.openshift.io/v1" -}}
{{- true -}}
{{- end -}}
{{- end -}}
