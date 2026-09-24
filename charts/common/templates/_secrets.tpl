{{/*
Secret lookup helpers.

Reuse existing cluster secret data on upgrade, or fall back to a default value.
Requires a live cluster connection (lookup does not work with helm template offline).
*/}}

{{/*
Return an existing secret value, or a base64-encoded default when the secret is missing.

Usage: include "vast.common.secrets.lookup" (dict "root" $ "secret" "secret-name" "key" "keyName" "defaultValue" .Values.myValue)
*/}}
{{- define "vast.common.secrets.lookup" -}}
{{- $root := required "root is required" .root -}}
{{- $secret := required "secret is required" .secret -}}
{{- $key := required "key is required" .key -}}
{{- $namespace := include "vast.common.namespace" $root | trimAll "\"" -}}
{{- $value := "" -}}
{{- $secretData := (lookup "v1" "Secret" $namespace $secret).data -}}
{{- if and $secretData (hasKey $secretData $key) -}}
{{- $value = index $secretData $key -}}
{{- else if .defaultValue -}}
{{- $value = .defaultValue | toString | b64enc -}}
{{- end -}}
{{- if $value -}}
{{- printf "%s" $value -}}
{{- end -}}
{{- end -}}

{{/*
Return true when a secret already exists in the release namespace.

Usage: include "vast.common.secrets.exists" (dict "root" $ "secret" "secret-name")
*/}}
{{- define "vast.common.secrets.exists" -}}
{{- $root := required "root is required" .root -}}
{{- $secret := required "secret is required" .secret -}}
{{- $namespace := include "vast.common.namespace" $root | trimAll "\"" -}}
{{- if lookup "v1" "Secret" $namespace $secret -}}
{{- true -}}
{{- end -}}
{{- end -}}
