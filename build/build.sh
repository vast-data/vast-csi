#!/bin/bash

set -e

VERSION=$(git describe --tags --abbrev=0)
GIT_COMMIT=$(git rev-parse HEAD)

docker build \
    -t vast-csi:dev \
    --cache-from vast-csi:dev \
    --build-arg=GIT_COMMIT=$GIT_COMMIT \
    --build-arg=VERSION=$VERSION \
    -f build/Dockerfile \
    .

if [[ $1 == "no-sanity" ]]; then
    echo "SKIPPING SANITY TESTS"
else
    ./ci/sanity.sh
fi

TARGETS=(
    vast-csi:latest
    vast-csi:$VERSION
    110450271409.dkr.ecr.eu-west-1.amazonaws.com/dev/vast-csi:latest
    110450271409.dkr.ecr.eu-west-1.amazonaws.com/dev/vast-csi:$VERSION
    )

for tag in ${TARGETS[@]}; do
    docker tag vast-csi:dev $tag
    echo "$tag"
done
