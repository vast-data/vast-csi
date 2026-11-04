# App layer for both UBI (CSI_BASE) and Distroless (CSI_BASE_DISTROLESS).
# version.info is written by scripts/build_images.py (Distroless has no shell for RUN).

ARG BASE_IMAGE
FROM $BASE_IMAGE

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID

COPY version.info.build version.info

COPY vast_csi vast_csi
COPY charts charts
COPY tests tests
COPY pyproject.toml .
COPY k8s_supported.txt .

LABEL \
    name="VAST CSI Driver" \
    vendor="VAST Data" \
    version=$VERSION \
    release="1" \
    summary="VAST CSI Driver" \
    description="VAST CSI Driver allows container orchestration frameworks such as Kubernetes to dynamically provision storage volumes on the VAST Data Platform. VAST provides scalable, reliable, and fast persistent storage that can be accessed remotely by any Kubernetes application container." \
    io.k8s.description="VAST CSI Driver allows container orchestration frameworks such as Kubernetes to dynamically provision storage volumes on the VAST Data Platform. VAST provides scalable, reliable, and fast persistent storage that can be accessed remotely by any Kubernetes application container." \
    license="Apache License" \
    maintainer="VAST Data" \
    io.k8s.display-name="VAST CSI Driver" \
    io.openshift.tags="vastdata,csi,vastdata-csi-driver"

ENTRYPOINT ["/root/.venv/bin/python", "-m", "vast_csi"]
