#!/bin/bash

set -e

VERSION=v2.3.0

docker build -t csi-sanity:$VERSION -<<EOF
FROM golang:latest
RUN git clone --branch $VERSION --depth 1 https://github.com/kubernetes-csi/csi-test.git
RUN cd csi-test/cmd/csi-sanity && make
EOF

docker run --rm -v `pwd`:/output csi-sanity:$VERSION cp /go/csi-test/cmd/csi-sanity/csi-sanity /output/
sudo install ./csi-sanity /usr/local/bin/
