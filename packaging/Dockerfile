# FROM python:3.6

FROM python:3.6-alpine

WORKDIR /root

COPY packaging/files .
# RUN apt-get update && apt-get install -y nfs-common && \
RUN apk add --no-cache nfs-utils build-base linux-headers && \
	pip install --no-cache-dir -r requirements.txt && \
	cd /usr/libexec/gcc/x86_64-alpine-linux-musl/*/ && rm -fv cc1 cc1obj cc1plus lto1

COPY vast_csi vast_csi
COPY deployment .

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID
RUN echo "$NAME $VERSION $GIT_COMMIT" > version.info 

LABEL name=$NAME
LABEL version=$VERSION.$GIT_COMMIT.$CI_PIPELINE_ID
LABEL vendor=vastdata

ENTRYPOINT ["python", "-m", "vast_csi"]
