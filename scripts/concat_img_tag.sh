#!/usr/bin/env bash

# Script to concatenate image name and tag/digest
# Usage: ./concat_img_tag.sh <image> <tag>

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <image> <tag>" >&2
  exit 1
fi

IMG="$1"
TAG="$2"

# Check if the tag starts with @sha256 (digest case)
if [[ "$TAG" =~ ^@sha256: ]]; then
  CONCATENATED="${IMG}${TAG}"   # No colon
else
  CONCATENATED="${IMG}:${TAG}"  # Regular tag with colon
fi

# Print the result
echo "$CONCATENATED"
