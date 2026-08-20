# Rebuild helm-operator from operator-sdk so Go modules can be bumped
# independently of the OpenShift ose-helm-rhel9-operator binary.
ARG OPERATOR_SDK_VERSION=v1.42.3
FROM golang:1.26 AS builder
ARG TARGETARCH
ARG OPERATOR_SDK_VERSION=v1.42.3

WORKDIR /workspace
RUN git clone --depth 1 --branch "${OPERATOR_SDK_VERSION}" \
        https://github.com/operator-framework/operator-sdk.git .
# Floors from Trivy on ose-helm-rhel9-operator:v4.21/v4.22 (ignore-unfixed).
RUN go get \
        helm.sh/helm/v3@v3.20.2 \
        google.golang.org/grpc@v1.82.1 \
        golang.org/x/crypto@v0.53.0 \
        golang.org/x/net@v0.56.0 \
        golang.org/x/text@v0.39.0 \
        golang.org/x/sys@v0.46.0 \
        golang.org/x/oauth2@v0.36.0 \
        github.com/containerd/containerd@v1.7.33 \
        github.com/moby/spdystream@v0.5.1 \
        github.com/google/cel-go@v0.29.0 \
        oras.land/oras-go/v2@v2.6.2 \
        go.opentelemetry.io/otel@v1.43.0 \
        go.opentelemetry.io/otel/sdk@v1.43.0 \
    && go mod tidy
RUN CGO_ENABLED=0 GOOS=linux GOARCH=${TARGETARCH:-amd64} \
        go build -tags=containers_image_openpgp \
        -ldflags "-X github.com/operator-framework/operator-sdk/internal/version.Version=${OPERATOR_SDK_VERSION} -X github.com/operator-framework/operator-sdk/internal/version.ImageVersion=${OPERATOR_SDK_VERSION}" \
        -o /helm-operator ./cmd/helm-operator

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.8

ARG VERSION

LABEL name="VAST CSI Operator" \
      vendor="VAST Data" \
      version="${VERSION}" \
      release="1" \
      summary="VAST CSI Operator" \
      description="VAST Data’s CSI Operator manages installation, upgrades, and configuration of the VAST CSI driver, enabling container orchestrators such as OpenShift Container Platform to easily integrate with the VAST Data Platform." \
      io.k8s.description="VAST Data’s CSI Operator manages installation, upgrades, and configuration of the VAST CSI driver, enabling container orchestrators such as OpenShift Container Platform to easily integrate with the VAST Data Platform." \
      license="Apache License" \
      maintainer="VAST Data" \
      io.k8s.display-name="VAST CSI Operator" \
      io.openshift.tags="vastdata,csi,vastdata-csi-driver"

ENV HOME=/opt/helm \
    USER_NAME=helm \
    USER_UID=1001

RUN microdnf upgrade -y \
    && microdnf clean all \
    && mkdir -p ${HOME} /licenses \
    && echo "${USER_NAME}:x:${USER_UID}:0:${USER_NAME} user:${HOME}:/sbin/nologin" >> /etc/passwd

COPY LICENSE /licenses/LICENSE
COPY --from=builder /helm-operator /usr/local/bin/helm-operator
COPY charts/vastcsi-operator/watches.yaml ${HOME}/watches.yaml
COPY charts/vastcsi-operator/crd-charts ${HOME}/helm-charts

RUN find ${HOME}/helm-charts -name "Chart.yaml" -exec sed -i.bak "s/^version: .*/version: ${VERSION}/" {} \; \
    && chown -R ${USER_UID}:0 ${HOME} /licenses

WORKDIR ${HOME}
USER ${USER_UID}

ENTRYPOINT ["/usr/local/bin/helm-operator", "run", "--watches-file=./watches.yaml"]
