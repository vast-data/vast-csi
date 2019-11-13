FROM golang:latest as builder
RUN git clone --branch v2.3.0 --depth 1 https://github.com/kubernetes-csi/csi-test.git
RUN cd csi-test/cmd/csi-sanity && make

FROM python:3.6
RUN apt-get update && \
	apt-get install -y nfs-common

WORKDIR /root

COPY --from=builder /go/csi-test/cmd/csi-sanity/csi-sanity /usr/bin/

COPY requirements.txt .
RUN pip install -r requirements.txt

RUN wget -q https://github.com/tigrawap/slit/releases/download/1.2.0/slit_linux_amd64 -O /tmp/slit && \
	chmod a+x /tmp/slit && \
	mv /tmp/slit /usr/bin/slit

COPY vast_csi vast_csi
COPY main.sh .

ARG NAME=com.vast.csi.plugin
ARG VERSION
ARG GIT_COMMIT
RUN echo "$NAME $VERSION $GIT_COMMIT" > version.info 

LABEL name=$NAME
LABEL version=$VERSION.$GIT_COMMIT
LABEL vendor=vastdata

ENTRYPOINT ["./main.sh"]