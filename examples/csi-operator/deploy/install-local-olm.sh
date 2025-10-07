#!/bin/bash

# VAST CSI Operator - Local Installation with OLM (using local manifests)
# This script installs the operator using OLM but with local manifests instead of bundle image

set -e

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_MANIFESTS_DIR="${SCRIPT_DIR}/../../../bundle/manifests"

# Default version
VERSION="${1:-v2.6.3}"

echo "Installing VAST CSI Operator (local OLM installation) version: $VERSION"

# Check if OLM is installed
if ! kubectl get crd clusterserviceversions.operators.coreos.com >/dev/null 2>&1; then
    echo "OLM is not installed. Please install OLM first:"
    echo "curl -sL https://github.com/operator-framework/operator-lifecycle-manager/releases/download/v0.34.0/install.sh | bash -s v0.34.0"
    exit 1
fi

# Clean up any existing installation
echo "Cleaning up any existing installation..."
kubectl delete csv "vast-csi-operator.${VERSION}" -n vast-csi --ignore-not-found=true
kubectl delete operatorgroup vast-csi-operator-group -n vast-csi --ignore-not-found=true
kubectl delete clusterrole vast-csi-operator --ignore-not-found=true
kubectl delete clusterrolebinding vast-csi-operator --ignore-not-found=true
kubectl delete namespace vast-csi --ignore-not-found=true

# Wait for cleanup
sleep 5

# Create namespace
echo "Creating namespace..."
kubectl create namespace vast-csi

# Create OperatorGroup
echo "Creating OperatorGroup..."
cat <<EOF | kubectl apply -f -
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: vast-csi-operator-group
  namespace: vast-csi
spec:
  targetNamespaces:
    - vast-csi
EOF

# Create ServiceAccount (OLM needs this to exist)
echo "Creating ServiceAccount..."
kubectl create serviceaccount vast-csi-driver-operator-controller-manager -n vast-csi

# Create ClusterRole and ClusterRoleBinding (OLM needs these for RBAC requirements)
echo "Creating ClusterRole and ClusterRoleBinding..."
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vast-csi-operator
rules:
- apiGroups: [""]
  resources: ["namespaces", "secrets", "events", "configmaps"]
  verbs: ["*"]
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["clusterrolebindings", "clusterroles", "rolebindings", "roles"]
  verbs: ["*"]
- apiGroups: ["security.openshift.io"]
  resources: ["securitycontextconstraints"]
  resourceNames: ["privileged", "hostmount-anyuid"]
  verbs: ["*"]
- apiGroups: ["storage.vastdata.com"]
  resources: ["vastcsidrivers", "vastcsidrivers/status", "vastcsidrivers/finalizers", "vaststorages", "vaststorages/status", "vaststorages/finalizers", "vastclusters", "vastclusters/status", "vastclusters/finalizers"]
  verbs: ["create", "delete", "get", "list", "patch", "update", "watch"]
- apiGroups: ["storage.k8s.io"]
  resources: ["csidrivers"]
  verbs: ["*"]
- apiGroups: ["apiextensions.k8s.io"]
  resources: ["customresourcedefinitions"]
  verbs: ["*"]
- apiGroups: [""]
  resources: ["serviceaccounts"]
  verbs: ["*"]
- apiGroups: ["rbac.authorization.k8s.io"]
  resources: ["rolebindings", "roles"]
  verbs: ["*"]
- apiGroups: ["apps"]
  resources: ["daemonsets", "deployments"]
  verbs: ["*"]
- apiGroups: ["storage.k8s.io"]
  resources: ["storageclasses"]
  verbs: ["*"]
- apiGroups: ["snapshot.storage.k8s.io"]
  resources: ["volumesnapshotclasses"]
  verbs: ["*"]
- apiGroups: ["coordination.k8s.io"]
  resources: ["leases"]
  verbs: ["get", "list", "watch", "create", "update", "delete"]
- apiGroups: ["authentication.k8s.io"]
  resources: ["tokenreviews"]
  verbs: ["create"]
- apiGroups: ["authorization.k8s.io"]
  resources: ["subjectaccessreviews"]
  verbs: ["create"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: vast-csi-operator
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: vast-csi-operator
subjects:
- kind: ServiceAccount
  name: vast-csi-driver-operator-controller-manager
  namespace: vast-csi
EOF

# Apply all manifests from bundle
echo "Applying all bundle manifests..."
kubectl apply -f "${BUNDLE_MANIFESTS_DIR}/" -n vast-csi

# Wait for CSV to be ready
echo "Waiting for ClusterServiceVersion to be ready..."
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded "csv/vast-csi-operator.${VERSION}" -n vast-csi --timeout=300s

echo "VAST CSI Operator installed successfully with OLM!"
echo ""
echo "Check the installation:"
echo "   kubectl get csv -n vast-csi"
echo "   kubectl get pods -n vast-csi"
echo ""
echo "Test the operator by creating a VastCSIDriver:"
echo "   kubectl apply -f examples/csi-operator/csidriver-block.yaml"
