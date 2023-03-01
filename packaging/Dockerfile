FROM python:3.9-alpine

WORKDIR /root

COPY packaging/files .
# RUN apt-get update && apt-get install -y nfs-common && \
RUN apk add --no-cache \
	# used by driver to mount
	nfs-utils \
	# used to compile grpcio
	linux-headers build-base && \
	pip install --no-cache-dir -r requirements.txt && \
	cd /usr/libexec/gcc/x86_64-alpine-linux-musl/*/ && rm -fv cc1 cc1obj cc1plus lto1

COPY vast_csi vast_csi
COPY deployment .
COPY k8s_supported.txt .

ARG NAME=csi.vastdata.com
ARG VERSION
ARG GIT_COMMIT
ARG CI_PIPELINE_ID
RUN echo "$NAME $VERSION $GIT_COMMIT" > version.info 

LABEL name=$NAME
LABEL version=$VERSION.$GIT_COMMIT.$CI_PIPELINE_ID
LABEL vendor=vastdata

ENTRYPOINT ["python", "-m", "vast_csi"]
