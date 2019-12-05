# FROM python:3.6

FROM python:3.6-alpine

WORKDIR /root

# for easier debugging
RUN wget -q https://github.com/tigrawap/slit/releases/download/1.2.0/slit_linux_amd64 -O /tmp/slit && \
	chmod a+x /tmp/slit && \
	mv /tmp/slit /usr/bin/slit

COPY packaging/files .
# RUN apt-get update && apt-get install -y nfs-common && \
RUN apk add --no-cache nfs-utils build-base linux-headers && \
	pip install --no-cache-dir -r requirements.txt && \
	cd /usr/libexec/gcc/x86_64-alpine-linux-musl/8.3.0/ && rm -fv cc1 cc1obj cc1plus lto1

COPY vast_csi vast_csi
COPY deployment .

ARG NAME=com.vastdata.csi.plugin
ARG VERSION
ARG GIT_COMMIT
RUN echo "$NAME $VERSION $GIT_COMMIT" > version.info 

LABEL name=$NAME
LABEL version=$VERSION.$GIT_COMMIT
LABEL vendor=vastdata

ENTRYPOINT ["python", "-m", "vast_csi"]
