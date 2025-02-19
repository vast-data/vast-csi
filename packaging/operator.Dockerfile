FROM registry.redhat.io/openshift4/ose-helm-operator

ARG VERSION
# Required OpenShift Labels
LABEL name="VAST CSI Operator"
LABEL vendor="VAST Data"
LABEL version="${VERSION}"
LABEL release="1"
LABEL summary="VAST CSI Operator"
LABEL description="VAST Data’s CSI Operator manages installation, upgrades, and configuration of the VAST CSI driver, enabling container orchestrators such as OpenShift Container Platform to easily integrate with the VAST Data Platform."

# Required Licenses
COPY LICENSE /licenses/LICENSE

ENV HOME=/opt/helm
COPY charts/vastcsi-operator/watches.yaml ${HOME}/watches.yaml
COPY charts/vastcsi-operator/crd-charts ${HOME}/helm-charts

# Update chart versions
RUN find ${HOME}/helm-charts -name "Chart.yaml" -exec sed -i.bak "s/^version: .*/version: $VERSION/" {} \;
WORKDIR ${HOME}
