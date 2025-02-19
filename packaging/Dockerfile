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
    name="VAST CSI Driver" \
    vendor="VAST Data" \
    version=$VERSION \
    release="1" \
    summary="VAST CSI Driver" \
    description="VAST CSI Driver allows container orchestration frameworks such as Kubernetes to dynamically provision storage volumes on the VAST Data Platform. VAST provides scalable, reliable, and fast persistent storage that can be accessed remotely by any Kubernetes application container."

ENTRYPOINT ["poetry", "run", "python", "-m", "vast_csi"]
