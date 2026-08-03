#!/usr/bin/env bash
# Apply VastCSIDriver + test namespace and wait for extension controller.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRIVER_NS="${DRIVER_NS:-vast-csi}"
TIMEOUT="${TIMEOUT:-300s}"

echo "Applying VastCSIDriver..."
kubectl apply -f "${ROOT_DIR}/manifests/01-vastcsidriver.yaml"

echo "Applying test namespace..."
kubectl apply -f "${ROOT_DIR}/manifests/02-test-namespace.yaml"

echo "Waiting for extension controller pod..."
kubectl wait --for=condition=ready pod \
  -l app=csi-vast-extension-controller \
  -n "${DRIVER_NS}" \
  --timeout="${TIMEOUT}"

echo "Extension controller is ready. Run:"
echo "  ${SCRIPT_DIR}/verify-webhook-certs.sh --functional"
