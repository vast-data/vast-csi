FROM registry.redhat.io/openshift4/ose-helm-operator:v4.15

ARG VERSION
# Required OpenShift Labels
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


# Required Licenses
COPY LICENSE /licenses/LICENSE

ENV HOME=/opt/helm
COPY charts/vastcsi-operator/watches.yaml ${HOME}/watches.yaml
COPY charts/vastcsi-operator/crd-charts ${HOME}/helm-charts

# Update chart versions
RUN find ${HOME}/helm-charts -name "Chart.yaml" -exec sed -i.bak "s/^version: .*/version: $VERSION/" {} \;
WORKDIR ${HOME}
