#!/bin/bash

set -e

log() { echo -e "\033[93m$(date $DATE_PARAM) >> $@\033[0m" 1>&2; }

VERSION=$(cat version.txt)
GIT_COMMIT=$(git rev-parse HEAD)

docker build \
    -t vast-csi:dev \
    --cache-from vast-csi:dev \
    --build-arg=GIT_COMMIT=$GIT_COMMIT \
    --build-arg=VERSION=$VERSION \
    --build-arg=VERSION=$CI_PIPELINE_ID \
    -f packaging/Dockerfile \
    .

if [[ $1 == "no-sanity" ]]; then
    log "SKIPPING SANITY TESTS"
else
    ./packaging/sanity.sh
    log "Done with sanity tests."
fi

log "Tagging as vast-csi:latest"
docker tag vast-csi:dev vast-csi:latest
