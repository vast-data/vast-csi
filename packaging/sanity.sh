#!/bin/sh

set -e

log() { echo -e "\033[92m$(date $DATE_PARAM) >> $@\033[0m" 1>&2; }

export VERSION=v4.3.0
docker build -t csi-sanity:$VERSION -<<EOF
FROM golang:latest
RUN git clone --branch $VERSION --depth 1 https://github.com/kubernetes-csi/csi-test.git
RUN cd csi-test/cmd/csi-sanity && make && mv /go/csi-test/cmd/csi-sanity/csi-sanity /
EOF

NETWORK=csi-test-net

docker kill test-subject 2> /dev/null || true
docker rm test-subject 2> /dev/null || true
docker volume rm -f csi-tests

docker network create $NETWORK 2> /dev/null || true

trap "(docker kill nfs test-subject; docker network rm $NETWORK; docker volume rm -f csi-tests) 1> /dev/null 2>&1 || true" exit

docker run -d --name nfs --rm --privileged --network $NETWORK erezhorev/dockerized_nfs_server

docker run \
    --init \
    --name test-subject \
    --network $NETWORK \
    --privileged \
    -v csi-tests:/tmp \
    -e PYTHONFAULTHANDLER=yes \
    -e CSI_ENDPOINT=0.0.0.0:50051 \
    -e X_CSI_MOCK_VAST=yes \
    -e X_CSI_SANITY_TEST=yes \
    -e X_CSI_NFS_SERVER=nfs \
    -e X_CSI_NFS_EXPORT=/exports \
    vast-csi:dev serve &


# -h \

if docker run \
    --name csi-sanity \
    --network $NETWORK \
    -v csi-tests:/tmp \
    --rm \
    csi-sanity:$VERSION \
    /csi-sanity \
    --ginkgo.failFast \
    --csi.endpoint=test-subject:50051 \
    --ginkgo.progress \
    --ginkgo.v \
    --ginkgo.seed=1; then
        log "All Good Bananas"
else
        log "Sanity test failed"
        exit 1
fi
