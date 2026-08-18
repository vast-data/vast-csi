#!/bin/bash
# Build vcsi CLI for multiple platforms (including Windows).
# Usage: VERSION=<version> ./scripts/build-multi-platform.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$ROOT/dist"
VERSION="${VERSION:-$(tr -d '[:space:]' < "$ROOT/vcsi_version" 2>/dev/null || echo "unknown")}"
GO_PROJECT="github.com/vast-data/vast-csi/extensions-controller"
GIT_COMMIT="${GIT_COMMIT:-$(git -C "$ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo "unknown")}"

echo "Building vcsi CLI for multiple platforms..."
echo "Root: $ROOT"
echo "Output directory: $OUTPUT_DIR"
echo "Version: $VERSION"
echo "Git commit: $GIT_COMMIT"
echo ""

mkdir -p "$OUTPUT_DIR"

cd "$ROOT"
go fmt ./cmd/... ./internal/... ./api/...
go vet ./cmd/... ./internal/... ./api/...

LDFLAGS="-s -w"
LDFLAGS+=" -X ${GO_PROJECT}/internal/common/version.GitCommit=${GIT_COMMIT}"
LDFLAGS+=" -X ${GO_PROJECT}/internal/common/version.Version=${VERSION}"

build_binary() {
    local GOOS=$1
    local GOARCH=$2
    local OUTPUT_NAME="vcsi-${GOOS}-${GOARCH}.${VERSION}"

    if [ "$GOOS" = "windows" ]; then
        OUTPUT_NAME="${OUTPUT_NAME}.exe"
    fi

    echo "Building ${OUTPUT_NAME}..."

    cd "$ROOT"
    GOOS=$GOOS GOARCH=$GOARCH CGO_ENABLED=0 go build \
        -ldflags "$LDFLAGS" \
        -a \
        -o "$OUTPUT_DIR/$OUTPUT_NAME" \
        cmd/main.go

    echo "Built ${OUTPUT_NAME}"
    echo ""
}

build_binary "linux" "amd64"
build_binary "linux" "arm64"
build_binary "darwin" "amd64"
build_binary "darwin" "arm64"
build_binary "windows" "amd64"
build_binary "windows" "arm64"

echo "All vcsi binaries built successfully"
echo ""
echo "Binaries in $OUTPUT_DIR:"
ls -lh "$OUTPUT_DIR"/vcsi-* 2>/dev/null || echo "No binaries found"
