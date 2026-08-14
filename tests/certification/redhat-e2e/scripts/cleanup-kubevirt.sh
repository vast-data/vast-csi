#!/bin/bash
#
# Cleanup script for kubevirt-storage-checkup resources
# Run this before retesting
#

set -e

NAMESPACE="vast-csi"
IMAGE_NS="openshift-virtualization-os-images"
GOLDEN_IMAGE_NAME="${GOLDEN_IMAGE_NAME:-fedora-coreos-golden-image}"

echo "=========================================="
echo "Cleaning Up Kubevirt Test Resources"
echo "=========================================="

echo ""
echo "[INFO] Cleaning up test job and configmap..."
oc delete job storage-checkup -n "$NAMESPACE" --ignore-not-found
oc delete configmap storage-checkup-config -n "$NAMESPACE" --ignore-not-found

echo ""
echo "[INFO] Cleaning up CDI prime/scratch PVCs in $IMAGE_NS ..."
while IFS= read -r pvc; do
  [[ -z "$pvc" ]] && continue
  oc delete pvc "$pvc" -n "$IMAGE_NS" --ignore-not-found || true
done < <(oc get pvc -n "$IMAGE_NS" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep '^prime-' || true)

echo ""
echo "[INFO] Cleaning up golden image resources (DataImportCron + hash DVs)..."
oc delete dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found
oc delete datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found
while IFS= read -r dv; do
  [[ -z "$dv" ]] && continue
  oc delete dv "$dv" -n "$IMAGE_NS" --ignore-not-found || true
  oc delete pvc "$dv" -n "$IMAGE_NS" --ignore-not-found || true
done < <(oc get dv -n "$IMAGE_NS" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep "^${GOLDEN_IMAGE_NAME}" || true)

echo ""
echo "[INFO] Cleaning up any test VMs and VMIs..."
oc delete vmi -l "kubevirt-vm=vmi-under-test" -n "$NAMESPACE" --ignore-not-found || true
oc delete vm -l "kubevirt-vm=vmi-under-test" -n "$NAMESPACE" --ignore-not-found || true

echo ""
echo "Cleanup complete!"
echo ""
echo "Next steps:"
echo "1. Run: ./run-kubevirt.sh"
echo "2. Verify golden image is discovered with: ./verify-golden-image.sh"
