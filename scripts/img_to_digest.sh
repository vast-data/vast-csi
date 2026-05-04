#!/bin/sh

# Check if the image tag was provided
if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <image:tag>" >&2
    exit 1
fi

IMAGE_TAG=$1

# Pull the image and extract the digest
PULL_STDERR=$(mktemp)
DIGEST=$(docker pull "$IMAGE_TAG" 2>"$PULL_STDERR" | awk '/Digest:/ {print $2}' | cut -d: -f2)
PULL_RC=$?

# Check if digest extraction was successful
if [ -z "$DIGEST" ] || [ "$PULL_RC" -ne 0 ]; then
    echo "Error: Failed to retrieve digest for image: $IMAGE_TAG" >&2
    echo "--- docker pull output ---" >&2
    cat "$PULL_STDERR" >&2
    rm -f "$PULL_STDERR"
    exit 1
fi
rm -f "$PULL_STDERR"

# Output only the digest
echo "@sha256:$DIGEST"
