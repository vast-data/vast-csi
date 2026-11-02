#!/usr/bin/env bash
# Verify a built CSI operator image embeds vendored vast-common and Helm-renders.
# Usage: IMAGE_TAG=<ref> ./scripts/verify_operator_image.sh
set -euo pipefail

: "${IMAGE_TAG:?ERROR: IMAGE_TAG is not set}"

log() { echo -e "\033[93m$(date) >> $*\033[0m" 1>&2; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

log "Inspecting operator image: $IMAGE_TAG"
cid=$(docker create "$IMAGE_TAG")
docker cp "$cid:/opt/helm/helm-charts" "$TMP/helm-charts"
docker rm "$cid" >/dev/null

missing=0
for chart_dir in "$TMP"/helm-charts/*; do
  [ -d "$chart_dir" ] || continue
  name=$(basename "$chart_dir")
  if [ -f "$chart_dir/Chart.yaml" ] && grep -q 'name: vast-common' "$chart_dir/Chart.yaml"; then
    if ! ls "$chart_dir"/charts/vast-common-*.tgz >/dev/null 2>&1; then
      log "ERROR: $name missing charts/vast-common-*.tgz"
      missing=1
    else
      log "OK: $name has $(basename "$(ls "$chart_dir"/charts/vast-common-*.tgz | head -1)")"
    fi
  fi
done
[ "$missing" -eq 0 ] || exit 1

VCD="$TMP/helm-charts/vastcsidriver"
[ -d "$VCD" ] || { log "ERROR: vastcsidriver chart missing from image"; exit 1; }

log "helm template vastcsidriver replicationEnabled=false"
helm template verify-driver "$VCD" --set driverType=nfs --set replicationEnabled=false >/dev/null

log "helm template vastcsidriver replicationEnabled=true"
helm template verify-driver "$VCD" --set driverType=nfs --set replicationEnabled=true >/dev/null

if [ -d "$TMP/helm-charts/vastextensionsmanager" ]; then
  log "helm template vastextensionsmanager"
  helm template verify-ext "$TMP/helm-charts/vastextensionsmanager" >/dev/null
fi

if [ -d "$TMP/helm-charts/vastcluster" ]; then
  log "helm template vastcluster"
  helm template verify-cluster "$TMP/helm-charts/vastcluster" \
    --set endpoint=https://vms.example.com --set username=u --set password=p >/dev/null
fi

log "verify_operator_image OK: $IMAGE_TAG"
