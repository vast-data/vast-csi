#!/bin/bash
#
# KubeVirt Storage Checkup Script for VastData CSI Driver
#
# Same flow as orion/pysrc/tests/csi/openshift/scripts/redhat-e2e/run-kubevirt.sh:
# 1. HTTP Fedora CoreOS qemu image (guest agent) on a 15Gi PVC
# 2. DataImportCron so kubevirt-storage-checkup can discover the golden image
# 3. cloneStrategy=copy (smart/snapshot clone is not used here)
#

set -euox pipefail

NAMESPACE="${1:-vast-csi}"
STORAGE_CLASS="${2:-vastdata-filesystem}"
GOLDEN_IMAGE_NAME="fedora-coreos-golden-image"
IMAGE_NS="openshift-virtualization-os-images"
FCOS_IMAGE_URL="https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/40.20240906.3.0/x86_64/fedora-coreos-40.20240906.3.0-qemu.x86_64.qcow2.xz"

echo "=========================================="
echo "KubeVirt Storage Checkup for VAST CSI"
echo "=========================================="
echo "Namespace: $NAMESPACE"
echo "Storage Class: $STORAGE_CLASS"
echo "Golden Image: $GOLDEN_IMAGE_NAME"
echo "=========================================="

echo "[INFO] Cleaning up previous test resources..."
oc delete job -n "$NAMESPACE" storage-checkup --ignore-not-found || true
oc delete configmap -n "$NAMESPACE" storage-checkup-config --ignore-not-found || true

RELEASE="${RELEASE:-$(curl -s https://storage.googleapis.com/kubevirt-prow/release/kubevirt/kubevirt/stable.txt)}"
echo "[INFO] KubeVirt version: $RELEASE"

echo "[INFO] Granting SCC permissions to KubeVirt service accounts..."
oc adm policy add-scc-to-user privileged -n kubevirt -z kubevirt-operator || true
oc adm policy add-scc-to-user privileged -n kubevirt -z kubevirt-controller || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-controller || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-api || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-handler || true

if ! oc get kv kubevirt -n kubevirt &>/dev/null; then
  echo "[INFO] Deploying KubeVirt operator and CR..."
  oc apply -f "https://github.com/kubevirt/kubevirt/releases/download/${RELEASE}/kubevirt-operator.yaml"
  oc apply -f "https://github.com/kubevirt/kubevirt/releases/download/${RELEASE}/kubevirt-cr.yaml"
else
  echo "[INFO] KubeVirt already deployed"
fi

echo "[INFO] Waiting for KubeVirt to be available..."
oc wait kv kubevirt -n kubevirt --for=condition=Available --timeout=15m

echo "[INFO] Configuring KubeVirt feature gates and emulation..."
oc patch kubevirt kubevirt -n kubevirt --type=merge -p '{
  "spec": {
    "configuration": {
      "developerConfiguration": {
        "featureGates": [
          "DataVolumes",
          "VMPersistentState",
          "HotplugVolumes"
        ],
        "useEmulation": true
      },
      "permittedHostDevices": {
        "pciHostDevices": [],
        "mediatedDevices": []
      }
    }
  }
}'
echo "[INFO] Restarting KubeVirt pods to apply configuration..."
oc delete pod -n kubevirt -l kubevirt.io=virt-controller --ignore-not-found || true
oc delete pod -n kubevirt -l kubevirt.io=virt-api --ignore-not-found || true
oc delete pod -n kubevirt -l kubevirt.io=virt-handler --ignore-not-found || true

if ! oc get cdi cdi -n cdi &>/dev/null; then
  echo "[INFO] Deploying CDI operator and CR..."
  oc apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
  oc apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml
else
  echo "[INFO] CDI already deployed"
fi

echo "[INFO] Waiting for CDI to be available..."
oc wait cdi cdi -n cdi --for=condition=Available --timeout=10m

oc adm policy add-scc-to-user privileged -n openshift-virtualization-os-images -z default || true
oc adm policy add-scc-to-user privileged -n cdi -z default || true

echo "[INFO] Configuring storage profile for VAST CSI (cloneStrategy=copy)..."
oc patch storageprofile "$STORAGE_CLASS" --type='merge' -p '
spec:
  claimPropertySets:
    - accessModes:
        - ReadWriteMany
      volumeMode: Filesystem
  cloneStrategy: copy
' || echo "[WARN] Failed to patch storage profile, continuing..."

echo "[INFO] Patching StorageProfiles with empty ClaimPropertySets..."
for sp in $(oc get storageprofile -o json | jq -r '.items[] | select((.status.claimPropertySets == null) or (.status.claimPropertySets | length == 0)) | .metadata.name'); do
  echo "[INFO] Patching StorageProfile: $sp"
  oc patch storageprofile "$sp" --type='merge' -p '{
    "spec": {
      "claimPropertySets": [
        {"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}
      ]
    }
  }' || echo "[WARN] Failed to patch StorageProfile $sp, continuing..."
done

echo "[INFO] Creating namespaces if they don't exist..."
oc create namespace "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
oc create namespace "$IMAGE_NS" --dry-run=client -o yaml | oc apply -f -

if ! oc get pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
  echo "[INFO] Creating Fedora CoreOS DataVolume with guest agent support..."
  echo "[INFO] This will download ~1.5GB image, please wait..."
  cat <<EOF | oc apply -f -
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: $GOLDEN_IMAGE_NAME
  namespace: $IMAGE_NS
  annotations:
    cdi.kubevirt.io/storage.bind.immediate.requested: "true"
  labels:
    instancetype.kubevirt.io/default-instancetype: u1.medium
    instancetype.kubevirt.io/default-preference: fedora
spec:
  source:
    http:
      url: "$FCOS_IMAGE_URL"
  storage:
    accessModes:
      - ReadWriteMany
    resources:
      requests:
        storage: 15Gi
    storageClassName: $STORAGE_CLASS
    volumeMode: Filesystem
EOF

  echo "[INFO] Waiting for DataVolume to be ready..."
  oc wait dv "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --for=condition=Ready --timeout=45m || {
    echo "[ERROR] DataVolume failed to become ready"
    oc describe dv "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS"
    exit 1
  }
else
  echo "[INFO] Golden image PVC already exists, checking labels..."
  oc annotate pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" \
    cdi.kubevirt.io/storage.bind.immediate.requested="true" --overwrite || true
  oc label pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" \
    instancetype.kubevirt.io/default-instancetype=u1.medium \
    instancetype.kubevirt.io/default-preference=fedora --overwrite || true
fi

echo "[INFO] Creating DataImportCron to make golden image discoverable..."
cat <<EOF | oc apply -f -
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataImportCron
metadata:
  name: $GOLDEN_IMAGE_NAME
  namespace: $IMAGE_NS
spec:
  garbageCollect: Outdated
  importsToKeep: 1
  managedDataSource: $GOLDEN_IMAGE_NAME
  schedule: "0 0 * * *"
  template:
    spec:
      source:
        registry:
          url: "docker://quay.io/containerdisks/fedora:40"
      storage:
        accessModes:
          - ReadWriteMany
        resources:
          requests:
            storage: 15Gi
        storageClassName: $STORAGE_CLASS
        volumeMode: Filesystem
EOF

echo "[INFO] Waiting for DataImportCron to complete initial import..."
for i in {1..90}; do
  LATEST_DV=$(oc get dv -n "$IMAGE_NS" -o json | \
    jq -r ".items[] | select(.metadata.name | startswith(\"$GOLDEN_IMAGE_NAME-\")) | .metadata.name" | \
    sort -r | head -n 1)

  if [[ -n "$LATEST_DV" ]]; then
    echo "[INFO] Found DataImportCron-managed DataVolume: $LATEST_DV"
    DV_PHASE=$(oc get dv "$LATEST_DV" -n "$IMAGE_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    echo "[INFO] Current phase: $DV_PHASE"

    if [[ "$DV_PHASE" == "Succeeded" ]]; then
      echo "[INFO] DataImportCron initial import completed successfully!"
      break
    elif [[ "$DV_PHASE" =~ ^(Failed|Unknown)$ ]]; then
      echo "[ERROR] DataImportCron import failed with phase: $DV_PHASE"
      oc describe dv "$LATEST_DV" -n "$IMAGE_NS"
      exit 1
    fi
  fi

  if [[ $i -eq 90 ]]; then
    echo "[ERROR] Timeout waiting for DataImportCron initial import to complete"
    oc get dv -n "$IMAGE_NS"
    exit 1
  fi

  echo "[INFO] Waiting for DataImportCron import... ($i/90)"
  sleep 10
done

echo "[INFO] Verifying DataSource is ready..."
for i in {1..30}; do
  DS_EXISTS=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.metadata.name}' 2>/dev/null || echo "")

  if [[ -n "$DS_EXISTS" ]]; then
    DS_PVC=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.spec.source.pvc.name}' 2>/dev/null || echo "")
    if [[ -n "$DS_PVC" ]]; then
      PVC_PHASE=$(oc get pvc "$DS_PVC" -n "$IMAGE_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
      if [[ "$PVC_PHASE" == "Bound" ]]; then
        echo "[INFO] DataSource is ready and references a bound PVC!"
        break
      fi
    fi
  fi

  if [[ $i -eq 30 ]]; then
    echo "[ERROR] DataSource not ready after 5 minutes"
    oc describe datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" || echo "DataSource not found"
    exit 1
  fi

  echo "[INFO] Waiting for DataSource to be ready... ($i/30)"
  sleep 10
done

echo "[INFO] Creating RBAC roles for storage checkup..."
oc apply -f - <<EOF
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vm-datavolume-creator
rules:
- apiGroups: ["cdi.kubevirt.io"]
  resources: ["datavolumes", "datavolumes/source"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: datavolume-source-reader
rules:
- apiGroups: ["cdi.kubevirt.io"]
  resources: ["datavolumes/source"]
  verbs: ["get", "list", "watch"]
EOF

echo "[INFO] Creating service account and permissions..."
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: storage-checkup-sa
  namespace: $NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: storage-checkup-sa-cluster-admin
subjects:
  - kind: ServiceAccount
    name: storage-checkup-sa
    namespace: $NAMESPACE
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
EOF

echo "[INFO] Creating role bindings..."
oc create rolebinding datavolume-source-reader-binding \
  --clusterrole=datavolume-source-reader \
  --serviceaccount="$NAMESPACE:storage-checkup-sa" \
  --namespace="$IMAGE_NS" \
  --dry-run=client -o yaml | oc apply -f -

oc create rolebinding vm-datavolume-creator-binding \
  --clusterrole=vm-datavolume-creator \
  --serviceaccount="$NAMESPACE:default" \
  --namespace="$IMAGE_NS" \
  --dry-run=client -o yaml | oc apply -f -

oc create rolebinding vm-datavolume-creator-local \
  --clusterrole=vm-datavolume-creator \
  --serviceaccount="$NAMESPACE:default" \
  --namespace="$NAMESPACE" \
  --dry-run=client -o yaml | oc apply -f -

echo "[INFO] Verifying golden image components are ready..."
DATASOURCE_READY=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "False")
PVC_STATUS=$(oc get pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
DATAIMPORTCRON_EXISTS=$(oc get dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o name 2>/dev/null || echo "")

if [[ "$DATASOURCE_READY" == "True" && "$PVC_STATUS" == "Bound" && -n "$DATAIMPORTCRON_EXISTS" ]]; then
  echo "[INFO] Golden image components ready:"
  echo "[INFO] - DataSource: Ready"
  echo "[INFO] - PVC: Bound ($( oc get pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.status.capacity.storage}'))"
  echo "[INFO] - DataImportCron: Present"
else
  echo "[ERROR] Golden image components not ready."
  echo "[INFO] DataSource: $DATASOURCE_READY"
  echo "[INFO] PVC: $PVC_STATUS"
  echo "[INFO] DataImportCron: $([ -n "$DATAIMPORTCRON_EXISTS" ] && echo "Present" || echo "Missing")"
  oc describe datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" || true
  oc describe pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" || true
  oc describe dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" || true
  exit 1
fi

echo "[INFO] Launching KubeVirt storage checkup job..."
cat <<EOF | oc apply -f -
apiVersion: v1
kind: ConfigMap
metadata:
  name: storage-checkup-config
  namespace: $NAMESPACE
data:
  spec.timeout: 30m
  spec.param.storageClass: $STORAGE_CLASS
  spec.param.vmiTimeout: 20m
  spec.param.goldenImage: $GOLDEN_IMAGE_NAME
  spec.param.goldenImageNamespace: $IMAGE_NS
  spec.param.numOfVMs: "2"
  spec.param.vmMemory: "512Mi"
---
apiVersion: batch/v1
kind: Job
metadata:
  name: storage-checkup
  namespace: $NAMESPACE
spec:
  backoffLimit: 0
  template:
    spec:
      serviceAccountName: storage-checkup-sa
      restartPolicy: Never
      containers:
        - name: storage-checkup
          image: quay.io/kiagnose/kubevirt-storage-checkup:main
          imagePullPolicy: Always
          env:
            - name: CONFIGMAP_NAMESPACE
              value: $NAMESPACE
            - name: CONFIGMAP_NAME
              value: storage-checkup-config
EOF

echo "[INFO] Waiting for storage-checkup pod to start..."
MAX_WAIT=30
COUNTER=0
while true; do
  POD=$(oc get pod -n "$NAMESPACE" -l job-name=storage-checkup -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "$POD" ]]; then
    PHASE=$(oc get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
    echo "[INFO] Pod $POD is in phase: $PHASE"
    [[ "$PHASE" =~ ^(Running|Succeeded|Failed)$ ]] && break
  fi

  COUNTER=$((COUNTER + 1))
  if [[ $COUNTER -ge $MAX_WAIT ]]; then
    echo "[ERROR] Timeout waiting for pod to start"
    exit 1
  fi
  sleep 1
done

echo "[INFO] Streaming logs from storage-checkup pod..."
echo "=========================================="
oc logs -f pod/"$POD" -n "$NAMESPACE" || true
echo "=========================================="

echo "[INFO] Final storage checkup result:"
oc get configmap storage-checkup-config -n "$NAMESPACE" -o yaml

FINAL_PHASE=$(oc get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
SUCCEEDED=$(oc get configmap storage-checkup-config -n "$NAMESPACE" -o jsonpath='{.data.status\.succeeded}' 2>/dev/null || echo "false")

if [[ "$FINAL_PHASE" == "Failed" ]] || [[ "$SUCCEEDED" == "false" ]]; then
  echo ""
  echo "========================================"
  echo "TEST FAILED - Collecting debug info..."
  echo "========================================"

  oc get vmi,vm -A || true
  oc get dv -A || true
  oc get pods -n "$NAMESPACE" -o wide || true
  oc get pods -A | grep virt-launcher || true
  oc get events -A --sort-by=.metadata.creationTimestamp | tail -n 50 || true
fi

echo ""
echo "========================================"
echo "Checking final test results..."
echo "========================================"
SUCCEEDED=$(oc get configmap storage-checkup-config -n "$NAMESPACE" -o jsonpath='{.data.status\.succeeded}' 2>/dev/null || echo "false")
FAILURE_REASON=$(oc get configmap storage-checkup-config -n "$NAMESPACE" -o jsonpath='{.data.status\.failureReason}' 2>/dev/null || echo "")

if [[ "$SUCCEEDED" == "true" ]]; then
  echo ""
  echo "KubeVirt storage checkup completed successfully!"
  echo "  oc get configmap storage-checkup-config -n $NAMESPACE -o yaml > kubevirt-checkup-results.yaml"
  echo ""
  exit 0
else
  echo ""
  echo "KubeVirt storage checkup failed."
  if [[ -n "$FAILURE_REASON" ]]; then
    echo "Failure reason: $FAILURE_REASON"
  fi
  echo "  oc get configmap storage-checkup-config -n $NAMESPACE -o yaml"
  echo ""
  exit 1
fi
