#!/bin/sh

set -e

log() { echo -e "\033[93m$(date $DATE_PARAM) >> $@\033[0m" 1>&2; }

VERSION=$(cat version.txt)
if [ -z $CI_COMMIT_SHA ]; then
    CI_COMMIT_SHA=$(git rev-parse HEAD)
fi

docker build \
    -t vast-csi:dev \
    --cache-from vast-csi:dev \
    --build-arg=MAINTAINER="ofer.koren@vastdata.com" \
    --build-arg=GIT_COMMIT=$CI_COMMIT_SHA \
    --build-arg=VERSION=$VERSION \
    --build-arg=CI_PIPELINE_ID=$CI_PIPELINE_ID \
    -f packaging/Dockerfile \
    .

if [ "$1" == "no-sanity" ]; then
    log "SKIPPING SANITY TESTS"
else
    ./packaging/sanity.sh
    log "Done with sanity tests."
fi

log "Tagging as vast-csi:latest"
docker tag vast-csi:dev vast-csi:latest
