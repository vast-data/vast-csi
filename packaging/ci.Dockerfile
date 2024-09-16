FROM docker:latest

RUN apk add --no-cache make curl bash git

# Install helm
RUN curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \
    && chmod 700 get_helm.sh \
    && ./get_helm.sh

# Install operator-sdk
RUN curl -LO https://github.com/operator-framework/operator-sdk/releases/download/v1.11.0/operator-sdk_linux_amd64 \
    && chmod +x operator-sdk_linux_amd64 \
    && mkdir -p /usr/local/bin/ \
    && mv operator-sdk_linux_amd64 /usr/local/bin/operator-sdk \
    && operator-sdk version

# Install preflight
RUN curl -LO https://github.com/redhat-openshift-ecosystem/openshift-preflight/releases/download/1.10.0/preflight-linux-amd64 \
    && chmod +x preflight-linux-amd64 \
    && mv preflight-linux-amd64 /usr/local/bin/preflight \
    && preflight version
