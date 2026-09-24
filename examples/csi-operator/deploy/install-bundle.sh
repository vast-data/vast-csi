#!/bin/bash

# VAST CSI Operator - Bundle Image Installation
# This script installs the operator from a Docker bundle image using operator-sdk

set -e

# Require bundle image as first argument
if [ -z "$1" ]; then
    echo "Error: Bundle image is required as first argument"
    echo "Usage: $0 <BUNDLE_IMAGE> [VERSION]"
    echo "Example: $0 quay.io/vastdata/vast-csi-operator-bundle:v2.7.0 v2.7.0"
    exit 1
fi

BUNDLE_IMAGE="$1"
VERSION="${2:-v2.7.0}"

echo "Installing VAST CSI Operator from bundle image: $BUNDLE_IMAGE (version: $VERSION)"

# Check if OLM is installed
if ! kubectl get crd clusterserviceversions.operators.coreos.com >/dev/null 2>&1; then
    echo "OLM is not installed. Please install OLM first:"
    echo "curl -sL https://github.com/operator-framework/operator-lifecycle-manager/releases/download/v0.34.0/install.sh | bash -s v0.34.0"
    exit 1
fi

# Check if operator-sdk is installed
if ! command -v operator-sdk &> /dev/null; then
    echo "operator-sdk is not installed. Please install operator-sdk first:"
    echo "https://sdk.operatorframework.io/docs/installation/"
    exit 1
fi

# Clean up any existing installation
echo "Cleaning up any existing installation..."
kubectl delete csv "vast-csi-operator.${VERSION}" -n vast-csi --ignore-not-found=true
kubectl delete operatorgroup vast-csi-operator-group -n vast-csi --ignore-not-found=true
kubectl delete catalogsource vast-csi-operator-catalog -n olm --ignore-not-found=true
kubectl delete catalogsource vast-csi-operator-catalog -n vast-csi --ignore-not-found=true
kubectl delete subscription vast-csi-operator -n vast-csi --ignore-not-found=true
kubectl delete namespace vast-csi --ignore-not-found=true

# Wait for cleanup
sleep 5

# Create namespace
echo "Creating namespace..."
kubectl create namespace vast-csi

# Install using operator-sdk run bundle
echo "Installing operator using operator-sdk run bundle..."

# Try to load the image into minikube first to avoid authentication issues
if command -v minikube &> /dev/null; then
    echo "Loading bundle image into minikube..."
    minikube image load "$BUNDLE_IMAGE" || echo "Warning: Could not load image into minikube, continuing anyway..."
fi

operator-sdk run bundle "$BUNDLE_IMAGE" \
    --namespace vast-csi \
    --timeout 20m

echo "VAST CSI Operator installed successfully from bundle image!"
echo ""
echo "Check the installation:"
echo "   kubectl get csv -n vast-csi"
echo "   kubectl get pods -n vast-csi"
echo ""
echo "Test the operator by creating a VastCSIDriver:"
echo "   kubectl apply -f examples/csi-operator/csidriver-block.yaml"
