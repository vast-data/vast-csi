#!/bin/bash

# Check if the image tag was provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <image:tag>" >&2
    exit 1
fi

IMAGE_TAG=$1

# Pull the image silently and extract the digest
DIGEST=$(docker pull "$IMAGE_TAG" 2>/dev/null | grep -oP 'Digest: sha256:\K[a-f0-9]+')

# Check if digest extraction was successful
if [ -z "$DIGEST" ]; then
    echo "Error: Failed to retrieve digest for image: $IMAGE_TAG" >&2
    exit 1
fi

# Output only the digest
echo "@sha256:$DIGEST"
