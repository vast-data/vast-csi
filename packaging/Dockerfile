ARG BASE_IMAGE_NAME
FROM $BASE_IMAGE_NAME

COPY packaging/files files

RUN pip install --no-cache-dir -r files/requirements.txt && rm -rf files
# Dynamically find the GCC directory and remove GCC files
RUN set -ex; \
    gcc_dirs=$(find /usr/libexec/gcc -mindepth 1 -maxdepth 1 -type d); \
    if [ -n "$gcc_dirs" ]; then \
        for gcc_dir in $gcc_dirs; do \
            echo "Found GCC directory: $gcc_dir"; \
            cd "$gcc_dir" && rm -fv cc1 cc1obj cc1plus lto1 || true; \
        done; \
    else \
        echo "No suitable GCC directories found."; \
    fi


COPY vast_csi vast_csi
COPY charts charts
COPY tests tests
COPY deployment .
COPY k8s_supported.txt .
# Required Licenses
COPY licenses /licenses

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID
RUN echo "$NAME $VERSION $GIT_COMMIT $CI_PIPELINE_ID" > version.info

LABEL \
    name="VASTData CSI Driver" \
    vendor="VASTData" \
    version="1.0.0" \
    release="1" \
    summary="VASTData CSI Driver" \
    description="This container image deploys the VASTData Container Storage Interface (CSI) driver. The CSI driver provides storage management and provisioning capabilities for containerized applications, allowing seamless integration with VASTData's storage solutions. It supports dynamic volume provisioning, snapshot management, and volume attachment operations for Kubernetes clusters."


ENTRYPOINT ["python", "-m", "vast_csi"]
