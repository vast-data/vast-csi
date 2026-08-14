#!/bin/bash
#
# Quick verification script to check if golden image is properly configured
# for kubevirt-storage-checkup discovery
#

set -e

GOLDEN_IMAGE_NAME="${GOLDEN_IMAGE_NAME:-fedora-coreos-golden-image}"
IMAGE_NS="openshift-virtualization-os-images"

echo "=========================================="
echo "Golden Image Verification"
echo "=========================================="

ACTIVE_PVC=""
if oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  ACTIVE_PVC=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.spec.source.pvc.name}' 2>/dev/null || echo "")
fi

echo ""
echo "1. Checking active golden image PVC (from DataSource)..."
if [[ -n "$ACTIVE_PVC" ]] && oc get pvc "$ACTIVE_PVC" -n "$IMAGE_NS" &>/dev/null; then
  echo "   ✅ Active PVC: $ACTIVE_PVC"
  PVC_STATUS=$(oc get pvc "$ACTIVE_PVC" -n "$IMAGE_NS" -o jsonpath='{.status.phase}')
  PVC_SIZE=$(oc get pvc "$ACTIVE_PVC" -n "$IMAGE_NS" -o jsonpath='{.status.capacity.storage}')
  echo "   Status: $PVC_STATUS"
  echo "   Size: $PVC_SIZE"
  SC=$(oc get pvc "$ACTIVE_PVC" -n "$IMAGE_NS" -o jsonpath='{.spec.storageClassName}')
  echo "   StorageClass: $SC"
else
  echo "   ❌ No bound active PVC from DataSource (expected ${GOLDEN_IMAGE_NAME}-<hash>)"
fi

echo ""
echo "2. Checking DataSource..."
if oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  echo "   ✅ DataSource exists"
  DS_READY=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
  echo "   Ready: $DS_READY"
else
  echo "   ❌ DataSource does not exist!"
fi

echo ""
echo "3. Checking DataImportCron..."
if oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  echo "   ✅ DataImportCron exists"
  DIC_STATUS=$(oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.status.conditions[?(@.type=="UpToDate")].status}' 2>/dev/null || echo "Unknown")
  CRON_STORAGE=$(oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.spec.template.spec.storage.resources.requests.storage}' 2>/dev/null || echo "")
  CRON_URL=$(oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.spec.template.spec.source.registry.url}' 2>/dev/null || echo "")
  echo "   UpToDate: $DIC_STATUS"
  echo "   Storage request: $CRON_STORAGE"
  echo "   Container disk: $CRON_URL"
else
  echo "   ❌ DataImportCron does not exist!"
  echo "   ⚠️  CRITICAL: kubevirt-storage-checkup requires DataImportCron to discover golden images!"
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="

ALL_GOOD=true

if [[ -z "$ACTIVE_PVC" ]] || ! oc get pvc "$ACTIVE_PVC" -n "$IMAGE_NS" &>/dev/null; then
  echo "❌ Active golden image PVC is missing"
  ALL_GOOD=false
fi

if ! oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  echo "❌ DataSource is missing"
  ALL_GOOD=false
fi

if ! oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  echo "❌ DataImportCron is missing"
  ALL_GOOD=false
fi

echo ""
if $ALL_GOOD; then
  echo "✅ All components present - golden image should be discovered!"
else
  echo "❌ Missing components - golden image will NOT be discovered!"
  echo ""
  echo "To fix, run the full setup script:"
  echo "  ./run-kubevirt.sh"
fi
