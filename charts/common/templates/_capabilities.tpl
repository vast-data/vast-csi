{{/*
Kubernetes and Helm capability helpers.

Use these to resolve the effective cluster version, compare semver constraints,
detect optional API groups, and pick stable apiVersion strings for core resources.

Helpers that take chart context expect the consuming chart root context ($).
Dictionary helpers use "root" for that context, consistent with other vast.common templates.
*/}}

{{/*
Return the effective Kubernetes version used for capability checks.

Resolution order: .Values.global.kubeVersion, then .Values.kubeVersion, then
.Capabilities.KubeVersion.Version from the target cluster or --kube-version.

Usage: include "vast.common.capabilities.kubeVersion" .
*/}}
{{- define "vast.common.capabilities.kubeVersion" -}}
{{- default (default .Capabilities.KubeVersion.Version .Values.kubeVersion) ((.Values.global).kubeVersion) -}}
{{- end -}}

{{/*
Return true when the effective Kubernetes version satisfies a semver constraint.

Usage: include "vast.common.capabilities.versionCompare" (dict "root" $ "constraint" ">=1.21-0")
*/}}
{{- define "vast.common.capabilities.versionCompare" -}}
{{- $root := required "root is required" .root -}}
{{- $constraint := required "constraint is required" .constraint -}}
{{- if semverCompare $constraint (include "vast.common.capabilities.kubeVersion" $root) -}}
{{- true -}}
{{- end -}}
{{- end -}}

{{/*
Return true when an API version is available in the target cluster.

When .Values.apiVersions or .Values.global.apiVersions is set, that list is treated
as authoritative. This supports offline rendering with helm template and helm lint.
Otherwise .Capabilities.APIVersions from the live cluster is used.

Usage: include "vast.common.capabilities.apiVersions.has" (dict "version" "monitoring.coreos.com/v1" "root" $)
*/}}
{{- define "vast.common.capabilities.apiVersions.has" -}}
{{- $root := required "root is required" .root -}}
{{- $version := required "version is required" .version -}}
{{- $providedAPIVersions := default $root.Values.apiVersions (($root.Values.global).apiVersions) -}}
{{- if and (empty $providedAPIVersions) ($root.Capabilities.APIVersions.Has $version) -}}
{{- true -}}
{{- else if has $version $providedAPIVersions -}}
{{- true -}}
{{- end -}}
{{- end -}}

{{/*
Return true when Helm 3.3+ is in use (.Capabilities.HelmVersion is available).

Helm versions before 3.3 do not expose .Capabilities.HelmVersion. The regex fallback
avoids "interface not found" errors when this helper is evaluated on older clients.

Usage: include "vast.common.capabilities.supportsHelmVersion" .
*/}}
{{- define "vast.common.capabilities.supportsHelmVersion" -}}
{{- if regexMatch "{(v[0-9])*[^}]*}}$" (.Capabilities | toString) -}}
{{- true -}}
{{- end -}}
{{- end -}}

{{/*
Return the apiVersion for apps/v1 workloads. VAST charts target modern Kubernetes only.

Usage: apiVersion: {{ include "vast.common.capabilities.deployment.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.deployment.apiVersion" -}}
apps/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.daemonset.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.daemonset.apiVersion" -}}
apps/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.rbac.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.rbac.apiVersion" -}}
rbac.authorization.k8s.io/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.crd.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.crd.apiVersion" -}}
apiextensions.k8s.io/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.storage.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.storage.apiVersion" -}}
storage.k8s.io/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.snapshot.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.snapshot.apiVersion" -}}
snapshot.storage.k8s.io/v1
{{- end -}}

{{/*
Usage: apiVersion: {{ include "vast.common.capabilities.admissionRegistration.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.admissionRegistration.apiVersion" -}}
admissionregistration.k8s.io/v1
{{- end -}}

{{/*
Return the PodDisruptionBudget apiVersion for the effective Kubernetes version.

Usage: apiVersion: {{ include "vast.common.capabilities.policy.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.policy.apiVersion" -}}
{{- if include "vast.common.capabilities.versionCompare" (dict "root" . "constraint" ">=1.21-0") -}}
policy/v1
{{- else -}}
policy/v1beta1
{{- end -}}
{{- end -}}

{{/*
Return the ServiceMonitor apiVersion for Prometheus Operator.

Pair with vast.common.capabilities.apiVersions.has before rendering CRD-backed resources.

Usage: apiVersion: {{ include "vast.common.capabilities.serviceMonitor.apiVersion" . }}
*/}}
{{- define "vast.common.capabilities.serviceMonitor.apiVersion" -}}
monitoring.coreos.com/v1
{{- end -}}
