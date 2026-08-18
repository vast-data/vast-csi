#!/usr/bin/env bash
# Verify extension webhook TLS secret, trust chain, mount, and optional admission test.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DRIVER_NS="${DRIVER_NS:-vast-csi}"
DRIVER_NAME="${DRIVER_NAME:-csi.vastdata.com}"
TEST_NS="${TEST_NS:-vast-webhook-cert-test}"
FUNCTIONAL=false

usage() {
  cat <<EOF
Usage: $(basename "$0") [--functional]

Environment:
  DRIVER_NS    Namespace of VastCSIDriver (default: vast-csi)
  DRIVER_NAME  VastCSIDriver metadata.name (default: csi.vastdata.com)
  TEST_NS      Namespace for admission test PVC (default: vast-webhook-cert-test)

Options:
  --functional   Also apply test PVC and verify admission succeeds (no x509 errors)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --functional) FUNCTIONAL=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

dns_safe() {
  echo "$1" | tr '.' '-' | cut -c1-63 | sed 's/-$//'
}

DNS_SAFE="$(dns_safe "${DRIVER_NAME}")"
SECRET="${DNS_SAFE}-vast-extension-controller-webhook-tls"
SVC="${DNS_SAFE}-vast-extension-controller-webhook"
MWC="${DNS_SAFE}-vast-extension-controller-webhook"
SVC_FQDN="${SVC}.${DRIVER_NS}.svc"

pass() { echo "  [PASS] $*"; }
fail() { echo "  [FAIL] $*" >&2; FAILURES=$((FAILURES + 1)); }

FAILURES=0

echo "Webhook TLS verification"
echo "  driver:  ${DRIVER_NAME} (namespace ${DRIVER_NS})"
echo "  secret:  ${SECRET}"
echo "  service: ${SVC_FQDN}"
echo

echo "== Static checks =="

if kubectl get secret "${SECRET}" -n "${DRIVER_NS}" >/dev/null 2>&1; then
  pass "Secret ${SECRET} exists"
else
  fail "Secret ${SECRET} not found in ${DRIVER_NS}"
fi

KEYS="$(kubectl get secret "${SECRET}" -n "${DRIVER_NS}" -o json 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin).get('data',{})
print(','.join(sorted(d.keys())))
" 2>/dev/null || true)"
if [[ -n "${KEYS}" && "${KEYS}" == *"tls.crt"* && "${KEYS}" == *"tls.key"* ]]; then
  pass "Secret contains tls.crt and tls.key"
else
  fail "Unexpected secret keys: ${KEYS:-<none>}"
fi

CERT_SUBJECT="$(kubectl get secret "${SECRET}" -n "${DRIVER_NS}" -o jsonpath='{.data.tls\.crt}' 2>/dev/null | base64 -d | openssl x509 -noout -subject 2>/dev/null || true)"
if [[ "${CERT_SUBJECT}" == *"${SVC_FQDN}"* ]]; then
  pass "Certificate subject references service DNS (${CERT_SUBJECT})"
else
  fail "Certificate subject mismatch: ${CERT_SUBJECT:-<parse failed>}; expected *${SVC_FQDN}*"
fi

CA_SECRET="$(kubectl get secret "${SECRET}" -n "${DRIVER_NS}" -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)"
CA_WEBHOOK="$(kubectl get mutatingwebhookconfiguration "${MWC}" -o jsonpath='{.webhooks[0].clientConfig.caBundle}' 2>/dev/null || true)"
INJECT_CA="$(kubectl get mutatingwebhookconfiguration "${MWC}" -o jsonpath='{.metadata.annotations.cert-manager\.io/inject-ca-from}' 2>/dev/null || true)"

if [[ "${CERT_MANAGER_MODE:-false}" == true ]]; then
  if [[ -n "${INJECT_CA}" ]]; then
    pass "MutatingWebhookConfiguration has cert-manager.io/inject-ca-from=${INJECT_CA}"
  else
    fail "Missing cert-manager.io/inject-ca-from annotation on ${MWC}"
  fi
  if [[ -n "${CA_WEBHOOK}" ]]; then
    pass "cainjector populated MWC caBundle"
  else
    fail "MWC caBundle empty — cainjector may not have run yet"
  fi
else
  if [[ -n "${CA_SECRET}" && "${CA_SECRET}" == "${CA_WEBHOOK}" ]]; then
    pass "MutatingWebhookConfiguration caBundle matches secret ca.crt"
  else
    fail "caBundle mismatch between secret and ${MWC}"
  fi
fi

POD="$(kubectl get pod -n "${DRIVER_NS}" -l app=csi-vast-extension-controller -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -z "${POD}" ]]; then
  fail "No extension controller pod found"
else
  MOUNT="$(kubectl get pod "${POD}" -n "${DRIVER_NS}" -o json | python3 -c "
import json,sys
pod=json.load(sys.stdin)
for c in pod['spec']['containers']:
    if c['name']!='extensions-webhook':
        continue
    for vm in c.get('volumeMounts',[]):
        if vm.get('name')=='webhook-tls':
            print(vm.get('mountPath',''))
            break
" 2>/dev/null || true)"
  if [[ "${MOUNT}" == "/tmp/k8s-webhook-server/serving-certs" ]]; then
    pass "extensions-webhook mounts webhook-tls at ${MOUNT}"
  else
    fail "extensions-webhook mount path unexpected: ${MOUNT:-<missing>}"
  fi
fi

if kubectl get svc "${SVC}" -n "${DRIVER_NS}" >/dev/null 2>&1; then
  pass "Webhook Service ${SVC} exists"
else
  fail "Webhook Service ${SVC} not found"
fi

echo
echo "== TLS handshake (in-cluster) =="

TLS_OUT="$(kubectl run "webhook-tls-probe-$$" \
  --restart=Never \
  -n "${DRIVER_NS}" \
  --image=docker.io/alpine:3.19 \
  --command -- sh -c \
  "apk add --no-cache openssl >/dev/null 2>&1; echo | openssl s_client -connect ${SVC_FQDN}:443 -servername ${SVC_FQDN} 2>/dev/null | openssl x509 -noout -subject" \
  2>/dev/null || true)"

# Wait for pod to complete
for _ in $(seq 1 30); do
  PHASE="$(kubectl get pod "webhook-tls-probe-$$" -n "${DRIVER_NS}" -o jsonpath='{.status.phase}' 2>/dev/null || true)"
  [[ "${PHASE}" == "Succeeded" || "${PHASE}" == "Failed" ]] && break
  sleep 2
done

PROBE_LOG="$(kubectl logs "webhook-tls-probe-$$" -n "${DRIVER_NS}" 2>/dev/null || true)"
kubectl delete pod "webhook-tls-probe-$$" -n "${DRIVER_NS}" --ignore-not-found >/dev/null 2>&1 || true

if [[ "${PROBE_LOG}" == *"${SVC_FQDN}"* ]]; then
  pass "TLS handshake returned cert for ${SVC_FQDN}"
else
  fail "TLS handshake failed or unexpected cert: ${PROBE_LOG:-${TLS_OUT:-<no output>}}"
fi

if [[ "${FUNCTIONAL}" == true ]]; then
  echo
  echo "== Functional admission test =="

  kubectl apply -f "${ROOT_DIR}/manifests/02-test-namespace.yaml" >/dev/null
  if kubectl apply -f "${ROOT_DIR}/manifests/03-test-storageclass-pvc.yaml" 2>"/tmp/webhook-cert-test-apply.err"; then
    pass "PVC CREATE admitted (no webhook TLS failure)"
    kubectl get pvc webhook-cert-test-pvc -n "${TEST_NS}" >/dev/null 2>&1 && \
      pass "PVC webhook-cert-test-pvc exists in ${TEST_NS}"
  else
    fail "PVC CREATE rejected — check /tmp/webhook-cert-test-apply.err"
    cat /tmp/webhook-cert-test-apply.err >&2
  fi
fi

echo
if [[ "${FAILURES}" -eq 0 ]]; then
  echo "All checks passed."
  exit 0
fi

echo "${FAILURES} check(s) failed."
exit 1
