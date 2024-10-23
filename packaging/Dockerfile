ARG BASE_IMAGE_NAME
FROM $BASE_IMAGE_NAME

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID
RUN echo "$NAME $VERSION $GIT_COMMIT $CI_PIPELINE_ID" > version.info

COPY vast_csi vast_csi
COPY charts charts
COPY tests tests
COPY k8s_supported.txt .

LABEL \
    name="VASTData CSI Driver" \
    vendor="VASTData" \
    version=$VERSION \
    release="1" \
    summary="VASTData CSI Driver" \
    description="This container image deploys the VASTData Container Storage Interface (CSI) driver. The CSI driver provides storage management and provisioning capabilities for containerized applications, allowing seamless integration with VASTData's storage solutions. It supports dynamic volume provisioning, snapshot management, and volume attachment operations for Kubernetes clusters."

ENTRYPOINT ["poetry", "run", "python", "-m", "vast_csi"]
