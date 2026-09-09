#!/usr/bin/env bash
# Generates charts/*/templates/replication.yaml:
#   - CSI-Addons operator stack (CRDs, RBAC, controller) from upstream release YAML
#   - VAST extension CRDs from config/crd/bases/
#
# Targets:
#   - charts/vastcsi/templates/replication.yaml              (full stack)
#   - charts/vastblock/templates/replication.yaml            (full stack)
#   - charts/vastcsi-operator/crd-charts/vastextensionsmanager/templates/replication.yaml  (CSI-Addons + VAST CRDs)
#
# Helm-templated fields in the controller deployment:
#   - vastcsi / vastblock: extensions.replication.csiAddonsImage, extensions.replication.maxGroupPvcs,
#     extensionController.resources.csiAddonsClusterManager
#   - vastextensionsmanager: image.csiAddonsController, replication.maxGroupPvcs, controller.resources.csiAddonsClusterManager
#
# Run via:  make sync-chart-crds  (from extensions-controller/)
# Or:       ./hack/sync-chart-crds.sh
set -euo pipefail

CSI_ADDONS_VERSION="${CSI_ADDONS_VERSION:-v0.14.0}"
CRD_DIR="config/crd/bases"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

BASE_URL="https://github.com/csi-addons/kubernetes-csi-addons/releases/download/${CSI_ADDONS_VERSION}"
echo "Fetching CSI-Addons ${CSI_ADDONS_VERSION} manifests..."
curl -fsSL "${BASE_URL}/crds.yaml" -o "${TMPDIR}/crds.yaml"
curl -fsSL "${BASE_URL}/rbac.yaml" -o "${TMPDIR}/rbac.yaml"
curl -fsSL "${BASE_URL}/setup-controller.yaml" -o "${TMPDIR}/setup-controller-upstream.yaml"

patch_setup_controller() {
    local src="$1"
    local dest="$2"
    local max_group_pvc_tpl="$3"
    local image_tpl="$4"
    local resources_tpl="$5"
    python3 <<PY
from pathlib import Path
import re

setup = Path("${src}")
text = setup.read_text()
needle = "        - --automaxprocs\n"
insert = (
    needle
    + "        - --max-group-pvc=${max_group_pvc_tpl}\n"
)
if needle not in text:
    raise SystemExit("setup-controller.yaml: expected --automaxprocs arg not found")
text = text.replace(needle, insert, 1)

image_tpl = """${image_tpl}"""
text, n = re.subn(
    r"^\s*image: quay\.io/csiaddons/k8s-controller:[^\n]+$",
    image_tpl,
    text,
    count=1,
    flags=re.MULTILINE,
)
if n != 1:
    raise SystemExit(f"setup-controller.yaml: expected 1 image line, replaced {n}")

resources_tpl = """${resources_tpl}"""
resources_re = re.compile(
    r"^        resources:\n(?:          .+\n)+",
    re.MULTILINE,
)
text, n = resources_re.subn(resources_tpl, text, count=1)
if n != 1:
    raise SystemExit(f"setup-controller.yaml: expected 1 resources block, replaced {n}")
Path("${dest}").write_text(text)
PY
}

MAX_GROUP_PVC_DEFAULT='{{ .Values.extensions.replication.maxGroupPvcs | default 10000 }}'
MAX_GROUP_PVC_ADDONS='{{ .Values.replication.maxGroupPvcs | default 10000 }}'
IMAGE_TPL_DEFAULT='        image: {{ .Values.extensions.replication.csiAddonsImage | default "quay.io/csiaddons/k8s-controller:v0.14.0" }}'
IMAGE_TPL_OPERATOR='        image: {{ .Values.extensions.replication.csiAddonsImage }}'
IMAGE_TPL_ADDONS='        image: {{ include "vastextensionsmanager.csiAddonsControllerImage" . }}'
RESOURCES_TPL_DEFAULT='        resources: {{- toYaml .Values.extensionController.resources.csiAddonsClusterManager | nindent 10 }}
'
RESOURCES_TPL_ADDONS='        resources: {{- toYaml .Values.controller.resources.csiAddonsClusterManager | nindent 10 }}
'

patch_setup_controller \
    "${TMPDIR}/setup-controller-upstream.yaml" \
    "${TMPDIR}/setup-controller.yaml" \
    "${MAX_GROUP_PVC_DEFAULT}" \
    "${IMAGE_TPL_DEFAULT}" \
    "${RESOURCES_TPL_DEFAULT}"

patch_setup_controller \
    "${TMPDIR}/setup-controller-upstream.yaml" \
    "${TMPDIR}/setup-controller-operator.yaml" \
    "${MAX_GROUP_PVC_DEFAULT}" \
    "${IMAGE_TPL_OPERATOR}" \
    "${RESOURCES_TPL_DEFAULT}"

patch_setup_controller \
    "${TMPDIR}/setup-controller-upstream.yaml" \
    "${TMPDIR}/setup-controller-addons.yaml" \
    "${MAX_GROUP_PVC_ADDONS}" \
    "${IMAGE_TPL_ADDONS}" \
    "${RESOURCES_TPL_ADDONS}"

patch_image_pull_secrets() {
    local dest="$1"
    python3 <<PY
from pathlib import Path

path = Path("${dest}")
text = path.read_text()
needle = "    spec:\n      containers:"
insert = """    spec:
{{- if .Values.imagePullSecrets }}
      imagePullSecrets:
{{ toYaml .Values.imagePullSecrets | indent 8 }}
{{- end }}
      containers:"""
if needle not in text:
    raise SystemExit(f"${dest}: expected pod spec containers block not found")
path.write_text(text.replace(needle, insert, 1))
PY
}

patch_image_pull_secrets "${TMPDIR}/setup-controller-addons.yaml"

patch_vastextensionsmanager_operator_stack() {
    local src="$1"
    local dest="$2"
    python3 <<PY
from pathlib import Path
import re

text = Path("${src}").read_text()
ns_tpl = 'namespace: {{ include "vastextensionsmanager.namespace" . }}'
text = text.replace("namespace: csi-addons-system", ns_tpl)
namespace_doc = (
    r"apiVersion: v1\nkind: Namespace\nmetadata:\n"
    r"(?:  [^\n]+\n)+"
    r"  name: csi-addons-system\n"
)
text, n = re.subn(rf"^{namespace_doc}---\n", "", text, count=1)
if n == 0:
    text, n = re.subn(rf"\n---\n{namespace_doc}", "\n", text, count=1)
# rbac.yaml has no Namespace document; setup-controller.yaml must have exactly one.
if "setup-controller" in "${src}" and n != 1:
    raise SystemExit(f"${src}: expected 1 Namespace document, removed {n}")
Path("${dest}").write_text(text)
PY
}

patch_vastextensionsmanager_operator_stack "${TMPDIR}/rbac.yaml" "${TMPDIR}/rbac-operator.yaml"
patch_vastextensionsmanager_operator_stack "${TMPDIR}/setup-controller-addons.yaml" "${TMPDIR}/setup-controller-operator-ns.yaml"

write_vastextensionsmanager_replication_yaml() {
    local dest="$1"
    local header_note="$2"

    {
        cat <<EOF
{{- /*
  ${header_note}
  CSI-Addons operator: upstream ${CSI_ADDONS_VERSION} release YAML (auto-generated).
  VAST CRDs: auto-generated by "make sync-chart-crds". DO NOT EDIT generated sections manually.
*/}}
# BEGIN AUTO-GENERATED CSI-ADDONS STACK ${CSI_ADDONS_VERSION}
EOF
        cat "${TMPDIR}/crds.yaml"
        echo "---"
        cat "${TMPDIR}/rbac-operator.yaml"
        echo "---"
        cat "${TMPDIR}/setup-controller-operator-ns.yaml"
        cat <<'EOF'
# END AUTO-GENERATED CSI-ADDONS STACK

# BEGIN AUTO-GENERATED VAST CRDS
# VastStorageClassReplication and VastVolumeReplication CRDs are owned by the
# CSI operator (OpenShift UI / OLM bundle) and are not installed from this chart.
# Helm-operator upgrades cannot reliably lookup existing CRDs, so shipping them
# here makes the VastExtensionsManager CR Irreconcilable.
EOF
        for f in "${CRD_DIR}"/*.yaml; do
            echo ''
            case "$(basename "$f")" in
              vastdata.com_vaststorageclassreplications.yaml|vastdata.com_vastvolumereplications.yaml)
                continue
                ;;
              *)
                cat "$f"
                ;;
            esac
        done
        echo ''
        echo '# END AUTO-GENERATED VAST CRDS'
    } > "$dest"
    echo "  ✓  ${dest}  ←  ${CSI_ADDONS_VERSION} + ${CRD_DIR}"
}

write_full_replication_yaml() {
    local dest="$1"
    local if_condition="$2"
    local header_note="$3"
    local setup_file="$4"
    local csi_addons_if='{{- if '"${if_condition}"' }}'
    local vast_if='{{- if '"${if_condition}"' }}'

    {
        cat <<EOF
{{- /*
  ${header_note}
  CSI-Addons operator: upstream ${CSI_ADDONS_VERSION} release YAML (auto-generated).
  Templated from values: image.csiAddonsController, replication.maxGroupPvcs, controller.resources.csiAddonsClusterManager
  VAST CRDs: auto-generated by "make sync-chart-crds". DO NOT EDIT generated sections manually.
*/}}
${csi_addons_if}
# BEGIN AUTO-GENERATED CSI-ADDONS STACK ${CSI_ADDONS_VERSION}
EOF
        cat "${TMPDIR}/crds.yaml"
        echo "---"
        cat "${TMPDIR}/rbac.yaml"
        echo "---"
        cat "${setup_file}"
        cat <<'EOF'
# END AUTO-GENERATED CSI-ADDONS STACK
{{- end }}

# BEGIN AUTO-GENERATED VAST CRDS
EOF
        for f in "${CRD_DIR}"/*.yaml; do
            echo ''
            echo "${vast_if}"
            cat "$f"
            echo '{{- end }}'
        done
        echo ''
        echo '# END AUTO-GENERATED VAST CRDS'
    } > "$dest"
    echo "  ✓  ${dest}  ←  ${CSI_ADDONS_VERSION} + ${CRD_DIR}"
}

write_full_replication_yaml \
    "../charts/vastblock/templates/replication.yaml" \
    ".Values.extensions.enabled" \
    "Replication stack installed when extensions are enabled." \
    "${TMPDIR}/setup-controller.yaml"

write_full_replication_yaml \
    "../charts/vastcsi/templates/replication.yaml" \
    ".Values.extensions.enabled" \
    "Replication stack installed when extensions are enabled." \
    "${TMPDIR}/setup-controller.yaml"

write_vastextensionsmanager_replication_yaml \
    "../charts/vastcsi-operator/crd-charts/vastextensionsmanager/templates/replication.yaml" \
    "Cluster-wide replication stack (singleton). Installed by VastExtensionsManager CR."
