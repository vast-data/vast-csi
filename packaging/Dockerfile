ARG BASE_IMAGE_NAME
FROM $BASE_IMAGE_NAME

COPY packaging/files files

RUN pip install --no-cache-dir -r files/requirements.txt && rm -rf files
# Dynamically find the GCC directory and remove GCC files
RUN set -ex; \
    gcc_dir=$(find /usr/libexec/gcc -mindepth 1 -maxdepth 1 -type d | grep -E "gcc/.*-alpine-linux-musl"); \
    if [ -n "$gcc_dir" ]; then \
        echo "Found GCC directory: $gcc_dir"; \
        cd "$gcc_dir" && rm -fv cc1 cc1obj cc1plus lto1; \
    else \
        echo "No suitable GCC directory found."; \
    fi


COPY vast_csi vast_csi
COPY charts charts
COPY tests tests
COPY deployment .
COPY k8s_supported.txt .

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID
RUN echo "$NAME $VERSION $GIT_COMMIT $CI_PIPELINE_ID" > version.info

LABEL name=$NAME
LABEL version=$VERSION.$GIT_COMMIT.$CI_PIPELINE_ID
LABEL vendor=vastdata

ENTRYPOINT ["python", "-m", "vast_csi"]
