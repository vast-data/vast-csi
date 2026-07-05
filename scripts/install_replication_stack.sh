#!/usr/bin/env bash
set -e

echo "=================================================="
echo "Volume Replication Stack Installation"
echo "=================================================="
echo ""

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Use v0.13.0 - latest version
# Note: Requires sidecar to use pod:// endpoint format and tokenreviews RBAC
CSI_ADDONS_VERSION="v0.13.0"

check_status() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ $1${NC}"
    else
        echo -e "${RED}❌ $1 failed${NC}"
        exit 1
    fi
}

echo "Using CSI-Addons version: ${CSI_ADDONS_VERSION}"
echo ""

# Step 0: Ensure namespace exists
echo "Step 0: Creating namespace"
echo "=========================="
echo ""

kubectl create namespace csi-addons-system 2>/dev/null || echo "Namespace already exists"
check_status "Namespace ready"

echo ""

# Step 1: Install ALL CRDs using the consolidated crds.yaml
echo "Step 1: Installing CSI-Addons CRDs"
echo "==================================="
echo ""

echo "Installing all CRDs from official release..."
kubectl apply -f https://github.com/csi-addons/kubernetes-csi-addons/releases/download/${CSI_ADDONS_VERSION}/crds.yaml
check_status "CRDs installed"

echo ""

# Step 2: Install RBAC
echo "Step 2: Installing RBAC Rules"
echo "=============================="
echo ""

echo "Installing RBAC from official release..."
kubectl apply -f https://github.com/csi-addons/kubernetes-csi-addons/releases/download/${CSI_ADDONS_VERSION}/rbac.yaml
check_status "RBAC installed"

echo ""

# Step 3: Install CSI-Addons Controller
echo "Step 3: Installing CSI-Addons Controller"
echo "========================================="
echo ""

echo "Installing controller from official release..."
kubectl apply -f https://github.com/csi-addons/kubernetes-csi-addons/releases/download/${CSI_ADDONS_VERSION}/setup-controller.yaml
check_status "Controller installed"

echo ""

# Step 4: Wait for controller to be ready
echo "Step 4: Waiting for Controller to be Ready"
echo "==========================================="
echo ""

NAMESPACE="csi-addons-system"
echo "Waiting for controller pod to be ready (timeout: 120s)..."
kubectl wait --for=condition=Ready pod -l app.kubernetes.io/name=csi-addons-controller-manager \
    -n $NAMESPACE --timeout=120s 2>/dev/null || {
    echo -e "${YELLOW}⚠️  Controller pod not ready yet, checking status...${NC}"
    kubectl get pods -n $NAMESPACE
    echo ""
    echo "Checking logs for issues..."
    kubectl logs -n $NAMESPACE -l app.kubernetes.io/name=csi-addons-controller-manager --tail=30 --all-containers=true 2>/dev/null || true
}

echo ""

# Step 5: Verification
echo "Step 5: Verification"
echo "===================="
echo ""

echo "Installed CRDs:"
kubectl get crd | grep -E "csiaddons|replication.storage.openshift.io"

echo ""
echo "Controller pods:"
kubectl get pods -n $NAMESPACE

echo ""
echo "Controller version:"
kubectl get deployment csi-addons-controller-manager -n $NAMESPACE -o jsonpath='{.spec.template.spec.containers[?(@.name=="manager")].image}' && echo ""

echo ""
echo -e "${GREEN}=================================================="
echo "✅ Installation Complete!"
echo "==================================================${NC}"
echo ""
echo "What was installed:"
echo "  • All CSI-Addons CRDs (including replication CRDs)"
echo "  • CSI-Addons Controller Manager (namespace: $NAMESPACE)"
echo "  • RBAC rules for all CSI-Addons features"
echo ""
echo "Version: ${CSI_ADDONS_VERSION}"
echo ""
echo "Installed CRDs include:"
echo "  • CSIAddonsNode"
echo "  • NetworkFence, NetworkFenceClass"
echo "  • ReclaimSpaceJob, ReclaimSpaceCronJob"
echo "  • EncryptionKeyRotationJob, EncryptionKeyRotationCronJob"
echo "  • VolumeReplication, VolumeReplicationClass"
echo "  • VolumeGroupReplication, VolumeGroupReplicationClass"
echo "  • VolumeGroupReplicationContent"
echo ""
echo "Verify installation:"
echo "  kubectl get pods -n $NAMESPACE"
echo "  kubectl get crd | grep replication"
echo "  kubectl get csiaddonsnodes -A"
echo ""
echo "Next steps:"
echo "  1. Deploy your CSI driver with replication enabled"
echo "  2. Create a PVC"
echo "  3. Enable replication with VolumeReplication CR"
echo "  4. Check status: kubectl get volumereplication -A"
echo ""
