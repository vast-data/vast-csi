{{/*
Extensions and CRD installation helpers.

Use these to avoid fighting over CRDs that may already be installed by another
Helm release (for example VastExtensionsManager).
*/}}

{{/*
Return "true" when this chart should emit a CRD manifest.

Install when the CRD is missing, or when it already belongs to the current
Helm release. Skip when another release owns it so upgrades do not conflict.

Usage: include "vast.common.extensions.shouldInstallCRD" (dict "root" $ "crdName" "example.example.com")
*/}}
{{- define "vast.common.extensions.shouldInstallCRD" -}}
{{- $root := required "root is required" .root -}}
{{- $crdName := required "crdName is required" .crdName -}}
{{- $existing := lookup "apiextensions.k8s.io/v1" "CustomResourceDefinition" "" $crdName -}}
{{- $owner := "" -}}
{{- if and $existing $existing.metadata $existing.metadata.annotations -}}
{{- $owner = index $existing.metadata.annotations "meta.helm.sh/release-name" | default "" -}}
{{- end -}}
{{- if or (not $existing) (eq $owner $root.Release.Name) -}}true{{- end -}}
{{- end -}}
