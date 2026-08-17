# Build the manager binary
FROM golang:1.25 AS builder
ARG TARGETOS
ARG TARGETARCH
ARG GIT_TAG
ARG GIT_COMMIT

WORKDIR /workspace
# Copy the Go Modules manifests
COPY extensions-controller/go.mod extensions-controller/go.sum ./
RUN go mod download

# Copy the go source
COPY extensions-controller/cmd/main.go cmd/main.go
COPY extensions-controller/api/ api/
COPY extensions-controller/internal/ internal/

# Build a statically linked binary (CGO_ENABLED=0) for ubi-micro runtime.
RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} \
    go build -ldflags \
    "-s -w -X github.com/vast-data/vast-csi/extensions-controller/internal/common/version.GitCommit=${GIT_COMMIT} \
    -X github.com/vast-data/vast-csi/extensions-controller/internal/common/version.Version=${GIT_TAG}" \
    -a -o manager cmd/main.go

# Red Hat certification requires a UBI-based runtime image (preflight rejects distroless).
# ubi-micro is the minimal UBI variant — suitable for static Go binaries.
FROM registry.access.redhat.com/ubi9/ubi-micro:9.6

ARG VERSION

# Required OpenShift / Red Hat certification labels
LABEL name="VAST CSI Extensions Manager" \
      vendor="VAST Data" \
      version="${VERSION}" \
      release="1" \
      summary="VAST CSI Extensions Manager" \
      description="VAST CSI Extensions Manager provides replication controllers, admission webhooks, and CSI-Addons integration for the VAST CSI driver on OpenShift." \
      io.k8s.description="VAST CSI Extensions Manager provides replication controllers, admission webhooks, and CSI-Addons integration for the VAST CSI driver on OpenShift." \
      license="Apache License" \
      maintainer="VAST Data" \
      io.k8s.display-name="VAST CSI Extensions Manager" \
      io.openshift.tags="vastdata,csi,vastdata-csi-extensions"

# Required license file for Red Hat certification
COPY LICENSE /licenses/LICENSE

COPY --from=builder /workspace/manager /manager

USER 65532:65532

ENTRYPOINT ["/manager"]
