#!/bin/bash

# Function to display usage information
usage() {
    echo "Usage: $0"
    echo
    echo "This script publishes a Docker image to the Red Hat registry and runs a preflight check for certification."
    echo
    echo "Required environment variables:"
    echo "  PROJECT_ID          - The project ID used for the Red Hat certification. (5f7595a16fd1fbdbe36c0b50 for CSI Driver and 66e6d0dd49f52e86c9d56b1c for Operator)"
    echo "  IMAGE_TAG           - The full tag of the image to be published."
    echo "  PYXIS_API_TOKEN     - The API token for Pyxis. (Can be found in the Red Hat certification project. (Product management -> Container API keys)"
    echo
    echo "Example:"
    echo "  export PROJECT_ID='your_project_id'"
    echo "  export IMAGE_TAG='quay.io/redhat-isv-containers/your_project_id:your_image_tag'"
    echo "  export PYXIS_API_TOKEN='your_pyxis_api_token'"
    echo "  ./run_preflight.sh"
    exit 1
}

# Ensure the script exits on any error
set -e

# Check for required environment variables
if [ -z "$PROJECT_ID" ] || [ -z "$IMAGE_TAG" ] || [ -z "$PYXIS_API_TOKEN" ]; then
    echo "Error: Missing required environment variables."
    usage
fi

# Run preflight check
echo "Running preflight check..."
preflight check container \
  "$IMAGE_TAG" \
  --submit \
  --pyxis-api-token="$PYXIS_API_TOKEN" \
  --certification-project-id="$PROJECT_ID" \
  --docker-config="$HOME/.docker/config.json"

echo "Image publication process completed successfully."
