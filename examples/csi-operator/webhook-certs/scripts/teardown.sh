#!/usr/bin/env bash
# Remove webhook cert test resources.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRIVER_NS="${DRIVER_NS:-vast-csi}"
DRIVER_NAME="${DRIVER_NAME:-csi.vastdata.com}"

echo "Removing test StorageClass/PVC..."
kubectl delete -f "${ROOT_DIR}/manifests/03-test-storageclass-pvc.yaml" --ignore-not-found

echo "Removing test namespace..."
kubectl delete -f "${ROOT_DIR}/manifests/02-test-namespace.yaml" --ignore-not-found

if [[ "${1:-}" == "--all" ]]; then
  echo "Removing VastCSIDriver ${DRIVER_NAME}..."
  kubectl delete vastcsidriver "${DRIVER_NAME}" -n "${DRIVER_NS}" --wait=true --timeout=240s || true
fi

echo "Done."
