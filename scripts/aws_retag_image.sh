#!/bin/bash

set -e

IMAGE=$1                # 110450271409.dkr.ecr.eu-west-1.amazonaws.com/dev/orion/hubble:keep-hubble-6
NEW_TAG=$2              # keep-hubble-latest

REGISTRY=${IMAGE%%/*}   # 110450271409.dkr.ecr.eu-west-1.amazonaws.com
SUFFIX=${IMAGE#*/}      # dev/orion/hubble:keep-hubble-6
REPO=${SUFFIX%%:*}      # dev/orion/hubble
OLD_TAG=${SUFFIX#*:}    # keep-hubble-6

MANIFEST=$(
    aws \
        --output=text \
        --query "images[0].imageManifest" \
        ecr batch-get-image \
            --repository-name $REPO \
            --image-ids imageTag=$OLD_TAG \
    )

# put new tag
aws --output=text \
    --query "image.imageId" \
    ecr put-image \
        --repository-name $REPO \
        --image-tag $NEW_TAG \
        --image-manifest "$MANIFEST"
