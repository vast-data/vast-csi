#!/bin/sh

set -e

log() { echo -e "\033[93m$(date $DATE_PARAM) >> $@\033[0m" 1>&2; }

# Check if the base image name is specified
if [ -z "$1" ]; then
    log "Base image name is not specified." && exit 1
fi

# Check if the tag is specified
if [ -z "$2" ]; then
    log "Tag is not specified." && exit 1
fi

BASE_IMAGE_NAME=$1
IMAGE_TAG=$2
VERSION=$(cat version.txt)
if [ -z "$CI_COMMIT_SHA" ]; then
    CI_COMMIT_SHA=$(git rev-parse HEAD)
fi

# Define target platforms
PLATFORMS="linux/amd64,linux/arm64"

# Create or use an existing Buildx builder instance
if ! docker buildx inspect builder > /dev/null 2>&1; then
    log "Creating a new Buildx builder instance."
    docker buildx create --name builder --use
else
    log "Using existing Buildx builder instance."
fi

# Build and push the Docker image
docker buildx build \
    --platform $PLATFORMS \
    -t $IMAGE_TAG \
    --build-arg=GIT_COMMIT=$CI_COMMIT_SHA \
    --build-arg=VERSION=$VERSION \
    --build-arg=CI_PIPELINE_ID=${CI_PIPELINE_ID:-local} \
    --build-arg=BASE_IMAGE_NAME=$BASE_IMAGE_NAME \
    -f packaging/Dockerfile \
    --push \
    .

# Log build completion
log "Build and push completed for image: $IMAGE_TAG for platforms: $PLATFORMS"
