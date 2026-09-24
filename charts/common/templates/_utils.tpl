{{/*
Values path utilities.
*/}}

{{/*
Get a nested value from .Values by dot-separated key path.

Usage: include "vast.common.utils.getValueFromKey" (dict "root" $ "key" "path.to.key")
*/}}
{{- define "vast.common.utils.getValueFromKey" -}}
{{- $root := required "root is required" .root -}}
{{- $key := required "key is required" .key -}}
{{- $splitKey := splitList "." $key -}}
{{- $value := "" -}}
{{- $latestObj := $root.Values -}}
{{- range $splitKey -}}
{{- if not $latestObj -}}
{{- printf "please review the entire path of '%s' exists in values" $key | fail -}}
{{- end -}}
{{- $value = (index $latestObj .) -}}
{{- $latestObj = $value -}}
{{- end -}}
{{- printf "%v" (default "" $value) -}}
{{- end -}}

{{/*
Return the first key in the list whose value is defined, or the first key if none are.

Usage: include "vast.common.utils.getKeyFromList" (dict "root" $ "keys" (list "path.to.key1" "path.to.key2"))
*/}}
{{- define "vast.common.utils.getKeyFromList" -}}
{{- $root := required "root is required" .root -}}
{{- $keys := required "keys is required" .keys -}}
{{- $key := first $keys -}}
{{- $reverseKeys := reverse $keys -}}
{{- range $reverseKeys -}}
{{- $value := include "vast.common.utils.getValueFromKey" (dict "key" . "root" $root) -}}
{{- if $value -}}
{{- $key = . -}}
{{- end -}}
{{- end -}}
{{- printf "%s" $key -}}
{{- end -}}
