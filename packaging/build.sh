#!/bin/sh

set -e

log() { echo -e "\033[93m$(date $DATE_PARAM) >> $@\033[0m" 1>&2; }

if [ -z "$1" ]; then
    log "Base image name is not specified." && exit 1
fi

BASE_IMAGE_NAME=$1
VERSION=$(cat version.txt)
if [ -z $CI_COMMIT_SHA ]; then
    CI_COMMIT_SHA=$(git rev-parse HEAD)
fi

docker build \
    -t vast-csi:dev \
    --cache-from vast-csi:latest \
    --build-arg=GIT_COMMIT=$CI_COMMIT_SHA \
    --build-arg=VERSION=$VERSION \
    --build-arg=CI_PIPELINE_ID=${CI_PIPELINE_ID:-local} \
    --build-arg=BASE_IMAGE_NAME=$BASE_IMAGE_NAME \
    -f packaging/Dockerfile \
    .

if [ "$1" == "--no-sanity" ]; then
    log "SKIPPING SANITY TESTS"
else
    ./packaging/sanity.sh
    log "Done with sanity tests."
fi

log "Tagging as vast-csi:latest"
docker tag vast-csi:dev vast-csi:latest
