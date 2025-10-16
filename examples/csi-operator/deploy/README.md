# VAST CSI Operator Installation

This directory contains scripts for installing the VAST CSI Operator locally for testing.

## Prerequisites

- **Kubernetes cluster**
- **kubectl** configured to access your cluster
- **OLM (Operator Lifecycle Manager)** installed

## Installation Methods

### 1. Local Installation with OLM

This method installs the operator using OLM with local manifests - no bundle image required.

```bash
./install-local-olm.sh [VERSION]
```

**What it does:**
- Creates namespace and OperatorGroup
- Creates ServiceAccount
- Applies CRDs from local bundle manifests
- Applies CSV from local bundle manifests
- OLM automatically creates the deployment from CSV
- Waits for the operator to be ready


### 2. Bundle Image Installation

This method installs the operator from a Docker bundle image using predefined manifests.


```bash
# Install operator from bundle image (BUNDLE_IMAGE is required)
./install-bundle.sh <BUNDLE_IMAGE> [VERSION]
```

**What it does:**
- Creates namespace and OperatorGroup
- Creates CatalogSource pointing to the bundle image
- Creates Subscription to install from CatalogSource
- OLM automatically creates the operator from the bundle

**Use this for production-like OLM workflows with bundle images**

## 3. Manual Bundle Image Update

If you prefer to manually update the bundle image in the manifests:

1. Edit `03-catalogsource.yaml` and update the image:
   ```yaml
   spec:
     image: quay.io/vastdata/vast-csi-operator-bundle:v2.6.4
   ```

2. Apply the manifests:
   ```bash
   kubectl apply -f 01-namespace.yaml
   kubectl apply -f 02-operatorgroup.yaml
   kubectl apply -f 03-catalogsource.yaml
   kubectl apply -f 04-subscription.yaml
   ```

## Testing the Installation

After installation, test the operator by creating a VastCSIDriver:

```bash
kubectl apply -f ../../csi-operator/csidriver-block.yaml
```

Check the installation:

```bash
# For local installation
kubectl get pods -n vast-csi

# For bundle installation
kubectl get csv -n vast-csi
kubectl get pods -n vast-csi
```

## Cleanup

To remove the operator:

```bash
# For local OLM installation
kubectl delete csv vast-csi-operator.v2.6.4 -n vast-csi
kubectl delete operatorgroup vast-csi-operator-group -n vast-csi
kubectl delete namespace vast-csi

# For bundle installation
kubectl delete csv vast-csi-operator.v2.6.4 -n vast-csi
kubectl delete operatorgroup vast-csi-operator-group -n vast-csi
kubectl delete catalogsource vast-csi-operator-catalog -n olm
kubectl delete subscription vast-csi-operator -n vast-csi
kubectl delete namespace vast-csi
```
