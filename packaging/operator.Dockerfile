FROM registry.redhat.io/openshift4/ose-helm-operator

ARG VERSION
# Required OpenShift Labels
LABEL name="VASTData CSI Driver Operator"
LABEL vendor="VASTData"
LABEL version="v${VERSION}"
LABEL release="1"
LABEL summary="VASTData CSI Driver Operator"
LABEL description="This operator will deploy VASTData CSI driver to the cluster."

# Required Licenses
COPY LICENSE /licenses/LICENSE

ENV HOME=/opt/helm
COPY charts/vastcsi-operator/watches.yaml ${HOME}/watches.yaml
COPY charts/vastcsi-operator/crd-charts ${HOME}/helm-charts

# Update chart versions
RUN find ${HOME}/helm-charts -name "Chart.yaml" -exec sed -i.bak "s/^version: .*/version: $VERSION/" {} \;
WORKDIR ${HOME}
