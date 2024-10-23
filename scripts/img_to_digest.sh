#!/bin/bash

# Check if the image tag was provided
if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <image:tag>" >&2
  exit 1
fi

IMAGE_TAG=$1

# Pull the image and suppress output
docker pull "$IMAGE_TAG" >/dev/null 2>&1

# Extract the image digest
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "$IMAGE_TAG" | awk -F '@' '{print $2}' 2>/dev/null)

# Check if digest extraction was successful
if [ -z "$DIGEST" ]; then
  echo "Failed to retrieve digest for image: $IMAGE_TAG" >&2
  exit 1
fi

echo "$DIGEST"