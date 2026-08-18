#!/usr/bin/env bash
# End-to-end cert-manager webhook TLS test (Certificate/Issuer outside Helm).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHART_DIR="${CHART_DIR:-/home/fnn45/VastData/vast-csi/charts/vastcsi-operator/crd-charts/vastcsidriver}"

DRIVER_NS="${DRIVER_NS:-vast-csi}"
DRIVER_NAME="${DRIVER_NAME:-csi.vastdata.com}"
DNS_SAFE="$(echo "${DRIVER_NAME}" | tr '.' '-' | cut -c1-63 | sed 's/-$//')"
SECRET="${DNS_SAFE}-vast-extension-controller-webhook-tls"
CERT_NAME="${DNS_SAFE}-vast-extension-controller-webhook-cert"
MWC="${DNS_SAFE}-vast-extension-controller-webhook"
TIMEOUT="${TIMEOUT:-300s}"

echo "== 1. Install cert-manager =="
"${SCRIPT_DIR}/install-cert-manager.sh"

echo "== 2. Apply Issuer + Certificate (outside Helm) =="
kubectl apply -f "${ROOT_DIR}/cert-manager/01-issuer.yaml"
kubectl apply -f "${ROOT_DIR}/cert-manager/02-certificate.yaml"

echo "Waiting for Certificate ${CERT_NAME}..."
kubectl wait --for=condition=ready "certificate/${CERT_NAME}" -n "${DRIVER_NS}" --timeout="${TIMEOUT}"

echo "== 3. Remove Helm-managed self-signed secret (if switching modes) =="
kubectl delete secret "${SECRET}" -n "${DRIVER_NS}" --ignore-not-found

echo "== 4. Helm upgrade with certManager.enabled=true (local chart) =="
helm upgrade "${DRIVER_NAME}" "${CHART_DIR}" -n "${DRIVER_NS}" \
  --reuse-values \
  --set extensions.enabled=true \
  --set extensions.webhook.enabled=true \
  --set extensions.webhook.certManager.enabled=true \
  --set extensions.webhook.certManager.certificateRef.name="${CERT_NAME}" \
  --set extensions.webhook.certManager.certificateRef.namespace="${DRIVER_NS}"

kubectl apply -f "${ROOT_DIR}/manifests/01-vastcsidriver-certmanager.yaml"

echo "Waiting for extension controller..."
kubectl wait --for=condition=ready pod -l app=csi-vast-extension-controller -n "${DRIVER_NS}" --timeout="${TIMEOUT}"

echo "== 5. Wait for cainjector to populate MWC caBundle =="
for _ in $(seq 1 60); do
  CABUNDLE="$(kubectl get mutatingwebhookconfiguration "${MWC}" -o jsonpath='{.webhooks[0].clientConfig.caBundle}' 2>/dev/null || true)"
  if [[ -n "${CABUNDLE}" ]]; then
    echo "caBundle populated."
    break
  fi
  sleep 5
done

if [[ -z "${CABUNDLE:-}" ]]; then
  echo "ERROR: MWC caBundle still empty. Check cainjector logs." >&2
  kubectl get certificate,secret -n "${DRIVER_NS}" | grep webhook || true
  kubectl get mutatingwebhookconfiguration "${MWC}" -o yaml | grep -A3 annotations || true
  exit 1
fi

echo "== 6. Run verification =="
CERT_MANAGER_MODE=true "${SCRIPT_DIR}/verify-webhook-certs.sh" --functional

echo "Cert-manager end-to-end test passed."
