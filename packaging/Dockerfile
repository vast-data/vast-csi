ARG BASE_IMAGE_NAME
FROM $BASE_IMAGE_NAME

COPY packaging/files files

RUN pip install --no-cache-dir -r files/requirements.txt && rm -rf files
RUN cd /usr/libexec/gcc/x86_64-alpine-linux-musl/*/ && rm -fv cc1 cc1obj cc1plus lto1

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
