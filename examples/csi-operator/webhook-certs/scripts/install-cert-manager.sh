#!/usr/bin/env bash
# Install cert-manager if not already present.
set -euo pipefail

CERT_MANAGER_VERSION="${CERT_MANAGER_VERSION:-v1.14.4}"
CERT_MANAGER_NAMESPACE="${CERT_MANAGER_NAMESPACE:-cert-manager}"

if kubectl get crd certificates.cert-manager.io >/dev/null 2>&1; then
  echo "cert-manager CRDs already installed."
else
  echo "Installing cert-manager ${CERT_MANAGER_VERSION}..."
  kubectl apply -f "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml"
fi

echo "Waiting for cert-manager webhook..."
kubectl wait --for=condition=available deployment/cert-manager-webhook \
  -n "${CERT_MANAGER_NAMESPACE}" --timeout=300s

kubectl wait --for=condition=available deployment/cert-manager \
  -n "${CERT_MANAGER_NAMESPACE}" --timeout=300s

echo "cert-manager is ready."
