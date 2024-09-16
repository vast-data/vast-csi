#!/bin/bash

# Function to display usage information
usage() {
    echo "Usage: $0"
    echo
    echo "This script publishes a Docker image to the Red Hat registry and runs a preflight check for certification."
    echo
    echo "Required environment variables:"
    echo "  REGISTRY_KEY        - The password for Docker registry login. Can be found in the Red Hat certification project. (Images -> Setup preflight)"
    echo "  PROJECT_ID          - The project ID used for the Red Hat certification. (5f7595a16fd1fbdbe36c0b50 for CSI Driver and 66e6d0dd49f52e86c9d56b1c for Operator)"
    echo "  SOURCE_IMAGE_ID     - The source image ID to be tagged and pushed. (Any image ID from VAST ECR)"
    echo "  TAG                 - The tag to apply to the image."
    echo "  PYXIS_API_TOKEN     - The API token for Pyxis. (Can be found in the Red Hat certification project. (Product management -> Container API keys)"
    echo
    echo "Example:"
    echo "  export REGISTRY_KEY='your_registry_key'"
    echo "  export PROJECT_ID='your_project_id'"
    echo "  export SOURCE_IMAGE_ID='your_source_image_id'"
    echo "  export TAG='your_image_tag'"
    echo "  export PYXIS_API_TOKEN='your_pyxis_api_token'"
    echo "  ./publish_to_redhat.sh"
    exit 1
}

# Ensure the script exits on any error
set -e

# Check for required environment variables
if [ -z "$REGISTRY_KEY" ] || [ -z "$PROJECT_ID" ] || [ -z "$SOURCE_IMAGE_ID" ] || [ -z "$TAG" ] || [ -z "$PYXIS_API_TOKEN" ]; then
    echo "Error: Missing required environment variables."
    usage
fi

# Docker login
echo "Logging into Docker registry..."
echo "$REGISTRY_KEY" | docker login -u "redhat-isv-containers+${PROJECT_ID}-robot" --password-stdin quay.io

# Tag image
echo "Tagging image..."
docker tag "$SOURCE_IMAGE_ID" "quay.io/redhat-isv-containers/${PROJECT_ID}:${TAG}"

# Push image
echo "Pushing image..."
docker push "quay.io/redhat-isv-containers/${PROJECT_ID}:${TAG}"

# Run preflight check
echo "Running preflight check..."
preflight check container \
  "quay.io/redhat-isv-containers/${PROJECT_ID}:${TAG}" \
  --submit \
  --pyxis-api-token="$PYXIS_API_TOKEN" \
  --certification-project-id="$PROJECT_ID" \
  --docker-config="$HOME/.docker/config.json"

echo "Image publication process completed successfully."
