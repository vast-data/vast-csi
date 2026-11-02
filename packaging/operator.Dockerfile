ARG OPERATOR_BASE_IMAGE_NAME
FROM $OPERATOR_BASE_IMAGE_NAME

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

USER root
ENV HOME=/opt/helm
COPY charts/vastcsi-operator/watches.yaml ${HOME}/watches.yaml
COPY charts/vastcsi-operator/crd-charts ${HOME}/helm-charts

# Fail the build if vast-common was not vendored (make operator-chart-deps / operator-build).
# Missing charts/vast-common-*.tgz causes ReleaseFailed: no template "vast.common.namespace".
RUN set -e; \
    for chart in ${HOME}/helm-charts/*; do \
      [ -d "$chart" ] || continue; \
      if [ -f "$chart/Chart.yaml" ] && grep -q 'name: vast-common' "$chart/Chart.yaml"; then \
        ls "$chart"/charts/vast-common-*.tgz >/dev/null 2>&1 \
          || { echo "ERROR: missing vendored vast-common in $chart (run: make operator-chart-deps)"; exit 1; }; \
      fi; \
    done

# Update chart versions
RUN find ${HOME}/helm-charts -name "Chart.yaml" -exec sed -i.bak "s/^version: .*/version: $VERSION/" {} \; \
    && chown -R 1001:0 ${HOME}
WORKDIR ${HOME}
USER 1001
