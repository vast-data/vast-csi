#!/usr/bin/env bash

set -e

log() { echo -e "\033[93m$(date) >> $@\033[0m" 1>&2; }

# Required environment variables
: "${IMAGE_TAG:?ERROR: IMAGE_TAG is not set.}"
: "${DOCKERFILE:?ERROR: DOCKERFILE is not set.}"

# Optional environment variables with defaults
BASE_IMAGE_NAME=${BASE_IMAGE_NAME:-""}
PLATFORMS=${PLATFORMS:-""}  # Default to empty if not provided
CACHE_FROM=${CACHE_FROM:-""} # Default to empty if not provided
PUSH_ON_SUCCESS=${PUSH_ON_SUCCESS:-"false"}  # Default to "false" if not provided
BUILD_CONTEXT=${BUILD_CONTEXT:-"."}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ -f "$DOCKERFILE" ]]; then
    DOCKERFILE_PATH="$(cd "$(dirname "$DOCKERFILE")" && pwd)/$(basename "$DOCKERFILE")"
elif [[ -f "$SCRIPT_DIR/$DOCKERFILE" ]]; then
    DOCKERFILE_PATH="$(cd "$SCRIPT_DIR/$(dirname "$DOCKERFILE")" && pwd)/$(basename "$DOCKERFILE")"
else
    log "ERROR" "Dockerfile not found: $DOCKERFILE" && exit 1
fi

if [[ "$BUILD_CONTEXT" != /* ]]; then
    BUILD_CONTEXT="$REPO_ROOT/$BUILD_CONTEXT"
fi

if [ ! -f version.txt ] || [ ! -s version.txt ]; then
    log "ERROR" "version.txt does not exist or is empty." && exit 1
fi

VERSION=$(cat version.txt)
GIT_TAG=${GIT_TAG:-$VERSION}

if [ -z "$CI_COMMIT_SHA" ]; then
    CI_COMMIT_SHA=$(git rev-parse HEAD || { log "ERROR" "Failed to get git commit SHA."; exit 1; })
fi

CACHE_FROM_ARG=""
if [ -n "$CACHE_FROM" ]; then
    CACHE_FROM_ARG="--cache-from $CACHE_FROM"
fi

if [ -n "$PLATFORMS" ]; then
    # Use Buildx if platforms are specified
    log "INFO" "Using Buildx for platforms: $PLATFORMS"
    if ! docker buildx inspect builder > /dev/null 2>&1; then
        log "INFO" "Creating a new Buildx builder instance."
        docker buildx create --name builder --use
    else
        log "INFO" "Using existing Buildx builder instance."
    fi
    # Build and push the Docker image using Buildx
    if ! docker buildx build \
        --platform "$PLATFORMS" \
        -t "$IMAGE_TAG" \
        $CACHE_FROM_ARG \
        --build-arg=GIT_COMMIT="$CI_COMMIT_SHA" \
        --build-arg=GIT_TAG="$GIT_TAG" \
        --build-arg=VERSION="$VERSION" \
        --build-arg=CI_PIPELINE_ID="${CI_PIPELINE_ID:-local}" \
        --build-arg=BASE_IMAGE_NAME="$BASE_IMAGE_NAME" \
        -f "$DOCKERFILE_PATH" \
        --push \
        "$BUILD_CONTEXT"; then
        log "ERROR" "Buildx build failed." && exit 1
    fi
else
    # Use standard Docker build if no platforms are specified
    if ! docker build \
        -t "$IMAGE_TAG" \
        $CACHE_FROM_ARG \
        --build-arg=GIT_COMMIT="$CI_COMMIT_SHA" \
        --build-arg=GIT_TAG="$GIT_TAG" \
        --build-arg=VERSION="$VERSION" \
        --build-arg=CI_PIPELINE_ID="${CI_PIPELINE_ID:-local}" \
        --build-arg=BASE_IMAGE_NAME="$BASE_IMAGE_NAME" \
        -f "$DOCKERFILE_PATH" \
        "$BUILD_CONTEXT"; then
        log "ERROR" "Docker build failed." && exit 1
    fi
    if [ "$PUSH_ON_SUCCESS" == "true" ]; then
        log "INFO" "Pushing image $IMAGE_TAG to specified registry."
        docker push "$IMAGE_TAG"
    fi
fi

# Log build completion
log "INFO" "Build and push completed for image: $IMAGE_TAG"
