#!/bin/bash

set -e

export VERSION=v2.3.0
docker build -t csi-sanity:$VERSION -<<EOF
FROM golang:latest
RUN git clone --branch $VERSION --depth 1 https://github.com/kubernetes-csi/csi-test.git
RUN cd csi-test/cmd/csi-sanity && make && mv /go/csi-test/cmd/csi-sanity/csi-sanity /
EOF

docker kill test-subject 2> /dev/null || true
docker rm test-subject 2> /dev/null || true

docker network create csi-net 2> /dev/null || true

trap "(docker kill nfs test-subject; docker network rm csi-net) 2> /dev/null || true" exit

docker run -d \
	--name nfs \
	--network csi-net \
	--rm \
    --mount type=tmpfs,tmpfs-size=512M,destination=/nfsshare \
	-e SHARED_DIRECTORY=/nfsshare \
	itsthenetwork/nfs-server-alpine:latest

docker run \
    --init \
	--name test-subject \
    --network csi-net \
    --privileged \
    -e PYTHONFAULTHANDLER=yes \
    -e CSI_ENDPOINT=0.0.0.0:50051 \
    -e X_CSI_MOCK_VAST=yes \
    -e X_CSI_SANITY_TEST=yes \
    -e X_CSI_NFS_SERVER=nfs \
    -e X_CSI_NFS_EXPORT=/ \
    vast-csi:dev &

if docker run \
	--name csi-sanity \
	--network csi-net \
	--rm \
	csi-sanity:$VERSION \
	/csi-sanity \
    -csi.endpoint=test-subject:50051 \
    -ginkgo.failFast \
    -ginkgo.progress \
    -ginkgo.debug; then
        echo "All Good Bananas"
else
        echo "Sanity test failed"
        exit 1
fi
