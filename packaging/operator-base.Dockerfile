# VAST CSI Operator base: rebuild helm-operator from operator-sdk onto UBI10.
# Built/pushed separately (like vast-csi-base), then consumed by operator.Dockerfile.

ARG GOLANG_IMAGE=golang:1.26.6
ARG OPERATOR_SDK_VERSION=v1.42.3

FROM ${GOLANG_IMAGE} AS builder
ARG TARGETARCH
ARG OPERATOR_SDK_VERSION

WORKDIR /workspace

# Clone a pinned operator-sdk release and build helm-operator with current Go.
RUN apt-get update && apt-get install -y --no-install-recommends git make \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 --branch "${OPERATOR_SDK_VERSION}" \
         https://github.com/operator-framework/operator-sdk.git .

# Floor modules so Trivy --ignore-unfixed clears findings in the binary.
# Use replace directives so transitive deps cannot pull older versions back.
# Floors track current Trivy DB (bump when new fixed CVEs appear in helm-operator).
RUN go get google.golang.org/grpc@v1.83.2 \
    && go get golang.org/x/crypto@v0.56.0 \
    && go get golang.org/x/net@v0.56.0 \
    && go get golang.org/x/text@v0.39.0 \
    && go get github.com/moby/spdystream@v0.5.1 \
    && go get github.com/containerd/containerd@v1.7.35 \
    && go get github.com/google/cel-go@v0.29.0 \
    && go get go.opentelemetry.io/otel@v1.45.0 \
    && go get go.opentelemetry.io/otel/sdk@v1.45.0 \
    && go get go.opentelemetry.io/otel/exporters/otlp/otlptrace@v1.45.0 \
    && go get go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@v1.45.0 \
    && go get helm.sh/helm/v3@v3.20.2 \
    && go get oras.land/oras-go/v2@v2.6.2 \
    && go mod edit \
         -replace=google.golang.org/grpc=google.golang.org/grpc@v1.83.2 \
         -replace=golang.org/x/crypto=golang.org/x/crypto@v0.56.0 \
         -replace=github.com/containerd/containerd=github.com/containerd/containerd@v1.7.35 \
         -replace=github.com/google/cel-go=github.com/google/cel-go@v0.29.0 \
         -replace=go.opentelemetry.io/otel=go.opentelemetry.io/otel@v1.45.0 \
         -replace=go.opentelemetry.io/otel/sdk=go.opentelemetry.io/otel/sdk@v1.45.0 \
         -replace=go.opentelemetry.io/otel/exporters/otlp/otlptrace=go.opentelemetry.io/otel/exporters/otlp/otlptrace@v1.45.0 \
         -replace=go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc=go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc@v1.45.0 \
         -replace=helm.sh/helm/v3=helm.sh/helm/v3@v3.20.2 \
    && go mod tidy \
    && GOOS=linux GOARCH=${TARGETARCH:-amd64} make build/helm-operator \
    && go version -m build/helm-operator | grep -E 'golang.org/x/crypto|containerd|cel-go|otel|helm.sh/helm'

FROM registry.access.redhat.com/ubi10/ubi-minimal:10.0

ENV HOME=/opt/helm \
    USER_NAME=helm \
    USER_UID=1001

USER root
RUN microdnf upgrade -y \
    && microdnf clean all \
    && echo "${USER_NAME}:x:${USER_UID}:0:${USER_NAME} user:${HOME}:/sbin/nologin" >> /etc/passwd \
    && mkdir -p "${HOME}" \
    && chown ${USER_UID}:0 "${HOME}"

COPY --from=builder /workspace/build/helm-operator /usr/local/bin/helm-operator

WORKDIR ${HOME}
USER ${USER_UID}

ENTRYPOINT ["/usr/local/bin/helm-operator", "run", "--watches-file=./watches.yaml"]
