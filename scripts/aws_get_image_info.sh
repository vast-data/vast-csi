#!/bin/bash

set -e

IMAGE=$1                # 110450271409.dkr.ecr.eu-west-1.amazonaws.com/dev/orion/hubble:keep-hubble-6
REGISTRY=${IMAGE%%/*}   # 110450271409.dkr.ecr.eu-west-1.amazonaws.com
SUFFIX=${IMAGE#*/}      # dev/orion/hubble:keep-hubble-6
REPO=${SUFFIX%%:*}      # dev/orion/hubble
TAG=${SUFFIX#*:}    # keep-hubble-6

echo 1>&2 "get token..."
TOKEN=$(aws ecr get-authorization-token --output text --query 'authorizationData[].authorizationToken')

echo 1>&2 "$REPO:$TAG: get digest..."
DIGEST=$(
    aws \
        --output=text \
        --query "images[0].imageManifest" \
        ecr batch-get-image \
            --repository-name $REPO \
            --image-ids imageTag=$TAG \
    | jq -r '.config.digest'
)

echo 1>&2 "$DIGEST: get config..."
curl --silent --location \
    --header "Authorization: Basic $TOKEN" \
    "https://$REGISTRY/v2/$REPO/blobs/$DIGEST"
