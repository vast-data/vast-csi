#!/usr/bin/env bash
# Launch Multipass VM with single-node k3s + VAST NFS for vast-csi e2e.
#
# Usage:  ./scripts/launch-multipass-k3s.sh
# Tear down: multipass delete --purge vast-csi-e2e
set -euo pipefail

NAME=vast-csi-e2e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_INIT="${SCRIPT_DIR}/multipass-k3s-cloud-init.yaml"
KUBECONFIG_OUT="$(cd "${SCRIPT_DIR}/.." && pwd)/kubeconfig.yaml"

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if ! command -v multipass &>/dev/null; then
  echo "ERROR: multipass is not installed" >&2
  exit 1
fi

if multipass info "${NAME}" &>/dev/null; then
  log "VM '${NAME}' already exists"
else
  log "Launching ${NAME}..."
  multipass launch 24.04 \
    --name "${NAME}" \
    --cpus 4 \
    --memory 8G \
    --disk 50G \
    --cloud-init "${CLOUD_INIT}" \
    --timeout 900
fi

log "Waiting for provisioning (VAST NFS + k3s, up to 30 min)..."
for _ in $(seq 1 180); do
  if multipass exec "${NAME}" -- test -f /var/lib/vast-csi-provisioned 2>/dev/null; then
    break
  fi
  sleep 10
done
if ! multipass exec "${NAME}" -- test -f /var/lib/vast-csi-provisioned 2>/dev/null; then
  echo "ERROR: provisioning timed out" >&2
  echo "Check: multipass exec ${NAME} -- sudo journalctl -u cloud-final" >&2
  exit 1
fi

# Multipass 1.16+ only supports table|json|csv|yaml (not Go templates).
ip="$(multipass info "${NAME}" | awk '/^IPv4:/{print $2; exit}')"
multipass exec "${NAME}" -- sudo cat /etc/rancher/k3s/k3s.yaml \
  | sed "s/127.0.0.1/${ip}/g" > "${KUBECONFIG_OUT}"
chmod 600 "${KUBECONFIG_OUT}"

log "Ready. export KUBECONFIG=${KUBECONFIG_OUT}"
multipass list
