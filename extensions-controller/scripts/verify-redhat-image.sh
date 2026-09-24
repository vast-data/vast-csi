#!/usr/bin/env bash
# Build the Extensions Manager image (UBI runtime) and run openshift-preflight
# locally before publishing to quay.io/redhat-isv-containers.
#
# Preflight pulls images from a registry, so this script pushes to a temporary
# local registry (localhost:5001) and runs checks with --insecure.
#
# Usage (from repo root):
#   ./extensions-controller/scripts/verify-redhat-image.sh
#
# Optional env:
#   PREFLIGHT_BIN   path to preflight binary (default: preflight in PATH, or /tmp/preflight-linux-amd64)
#   LOCAL_REGISTRY  host:port for temp registry (default: localhost:5001)
#   IMAGE_TAG       local image name (default: vast-csi-extensions:preflight-test)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

LOCAL_REGISTRY="${LOCAL_REGISTRY:-localhost:5001}"
LOCAL_IMAGE="${IMAGE_TAG:-vast-csi-extensions:preflight-test}"
REGISTRY_IMAGE="${LOCAL_REGISTRY}/vast-csi-extensions"
VERSION="$(sed 's/^v//' version.txt)"
GIT_TAG="$(cat version.txt)"
GIT_COMMIT="$(git rev-parse HEAD)"
ARTIFACTS="${PREFLIGHT_ARTIFACTS:-/tmp/preflight-extensions-artifacts}"
REGISTRY_NAME="preflight-extensions-registry"

preflight_bin() {
  if [ -n "${PREFLIGHT_BIN:-}" ] && [ -x "$PREFLIGHT_BIN" ]; then
    echo "$PREFLIGHT_BIN"
    return
  fi
  if command -v preflight >/dev/null 2>&1; then
    command -v preflight
    return
  fi
  local bin="/tmp/preflight-linux-amd64"
  if [ ! -x "$bin" ]; then
    echo "Downloading openshift-preflight 1.19.2..."
    curl -fsSL -o "$bin" \
      https://github.com/redhat-openshift-ecosystem/openshift-preflight/releases/download/1.19.2/preflight-linux-amd64
    chmod +x "$bin"
  fi
  echo "$bin"
}

cleanup() {
  docker rm -f "$REGISTRY_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Building image (UBI micro runtime)..."
docker build \
  --build-arg GIT_COMMIT="$GIT_COMMIT" \
  --build-arg GIT_TAG="$GIT_TAG" \
  --build-arg VERSION="$VERSION" \
  -f extensions-controller/Dockerfile \
  -t "$LOCAL_IMAGE" \
  .

echo "==> Verifying binary starts..."
docker run --rm "$LOCAL_IMAGE" --help >/dev/null

echo "==> Starting local registry on ${LOCAL_REGISTRY}..."
docker rm -f "$REGISTRY_NAME" >/dev/null 2>&1 || true
docker run -d --name "$REGISTRY_NAME" -p "${LOCAL_REGISTRY#localhost:}:5000" registry:2 >/dev/null
sleep 2

echo "==> Pushing to ${REGISTRY_IMAGE}:${VERSION}..."
docker tag "$LOCAL_IMAGE" "${REGISTRY_IMAGE}:${VERSION}"
docker push "${REGISTRY_IMAGE}:${VERSION}"

PF="$(preflight_bin)"
echo "==> Running preflight ($PF)..."
rm -rf "$ARTIFACTS"
mkdir -p "$ARTIFACTS"
"$PF" check container "${REGISTRY_IMAGE}:${VERSION}" \
  --insecure \
  --artifacts="$ARTIFACTS"

echo "==> Preflight PASSED. Artifacts: $ARTIFACTS"
