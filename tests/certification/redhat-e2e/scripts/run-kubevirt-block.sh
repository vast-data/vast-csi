#!/bin/bash
set -euox pipefail

NAMESPACE="${1:-vast-csi}"
STORAGE_CLASS="${2:-vastdata-block}"
GOLDEN_IMAGE_NAME="fedora-coreos-golden-image"
IMAGE_NS="openshift-virtualization-os-images"

# Clean up any old failed DataVolumes/PVCs from previous runs
oc delete dv -n "$IMAGE_NS" -l cdi.kubevirt.io/dataImportCron="$GOLDEN_IMAGE_NAME" --ignore-not-found || true
oc delete pvc -n "$IMAGE_NS" -l cdi.kubevirt.io/dataImportCron="$GOLDEN_IMAGE_NAME" --ignore-not-found || true
oc delete dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found || true
oc delete datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found || true

# Note: virtctl is not required for kubevirt-storage-checkup (uses oc + in-cluster job only).

RELEASE="${RELEASE:-$(curl -s https://storage.googleapis.com/kubevirt-prow/release/kubevirt/kubevirt/stable.txt)}"

# Grant SCC to KubeVirt service accounts
oc adm policy add-scc-to-user privileged -n kubevirt -z kubevirt-operator || true
oc adm policy add-scc-to-user privileged -n kubevirt -z kubevirt-controller || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-controller || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-api || true
oc adm policy add-scc-to-user privileged -n kubevirt -z virt-handler || true

# Deploy KubeVirt if not already deployed
if ! oc get kv kubevirt -n kubevirt &>/dev/null; then
  oc apply -f "https://github.com/kubevirt/kubevirt/releases/download/${RELEASE}/kubevirt-operator.yaml"
  oc apply -f "https://github.com/kubevirt/kubevirt/releases/download/${RELEASE}/kubevirt-cr.yaml"
fi

oc wait kv kubevirt -n kubevirt --for=condition=Available --timeout=5m

# Configure KubeVirt
oc patch kubevirt kubevirt -n kubevirt --type=merge -p '{
  "spec": {
    "configuration": {
      "developerConfiguration": {
        "featureGates": ["DataVolumes", "VMPersistentState", "HotplugVolumes"],
        "useEmulation": true
      }
    }
  }
}'
oc delete pod -n kubevirt -l kubevirt.io=virt-controller --ignore-not-found || true
oc delete pod -n kubevirt -l kubevirt.io=virt-api --ignore-not-found || true
oc delete pod -n kubevirt -l kubevirt.io=virt-handler --ignore-not-found || true

# Install CDI if not already deployed
if ! oc get cdi cdi -n cdi &>/dev/null; then
  oc apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml
  oc apply -f https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml
fi

oc wait cdi cdi -n cdi --for=condition=Available --timeout=5m

# Configure CDI to use filesystem storage class for scratch space (required for block volume imports)
# CDI needs filesystem scratch space even when importing to block volumes
oc patch cdi cdi -n cdi --type=merge -p '{
  "spec": {
    "config": {
      "scratchSpaceStorageClass": "vastdata-filesystem"
    }
  }
}' || true

# Verify CDI configuration was applied
SCRATCH_SC=$(oc get cdi cdi -n cdi -o jsonpath='{.spec.config.scratchSpaceStorageClass}' 2>/dev/null || echo "")
if [[ "$SCRATCH_SC" != "vastdata-filesystem" ]]; then
  echo "Warning: CDI scratch space storage class not set correctly. Current value: $SCRATCH_SC"
  echo "Retrying patch..."
  oc patch cdi cdi -n cdi --type=merge -p '{"spec":{"config":{"scratchSpaceStorageClass":"vastdata-filesystem"}}}'
fi

# Restart CDI pods to apply scratch space configuration
oc delete pod -n cdi -l cdi.kubevirt.io=cdi-controller --ignore-not-found || true
oc delete pod -n cdi -l cdi.kubevirt.io=cdi-uploadproxy --ignore-not-found || true
oc delete pod -n cdi -l cdi.kubevirt.io=cdi-apiserver --ignore-not-found || true
oc delete pod -n cdi -l app=containerized-data-importer --ignore-not-found || true
sleep 10
# Wait for CDI to be available again
oc wait cdi cdi -n cdi --for=condition=Available --timeout=3m || true

# Verify scratch space storage class is in CDI configmap (CDI reads from configmap)
CDI_CM_SC=$(oc get configmap cdi-config -n cdi -o jsonpath='{.data.scratchSpaceStorageClass}' 2>/dev/null || echo "")
if [[ "$CDI_CM_SC" != "vastdata-filesystem" ]]; then
  echo "Warning: CDI configmap doesn't have scratch space storage class set"
  echo "CDI configmap value: $CDI_CM_SC"
  echo "This might cause scratch space to use the wrong storage class"
fi

# Patch storage profile for block storage class with Filesystem mode
oc patch storageprofile "$STORAGE_CLASS" --type='merge' -p '
spec:
  claimPropertySets:
    - accessModes:
        - ReadWriteOnce
      volumeMode: Filesystem
  cloneStrategy: copy
' || true

# Create namespaces
oc create namespace "$NAMESPACE" --dry-run=client -o yaml | oc apply -f -
oc create namespace "$IMAGE_NS" --dry-run=client -o yaml | oc apply -f -

# Clean up any old DataImportCron and related resources that might have registry source
oc delete dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found || true
oc delete datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found || true
sleep 2

# Create Fedora CoreOS DataVolume for block storage
if ! oc get pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" &>/dev/null; then
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
      url: "https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/40.20240906.3.0/x86_64/fedora-coreos-40.20240906.3.0-qemu.x86_64.qcow2.xz"
  storage:
    accessModes:
      - ReadWriteOnce
    resources:
      requests:
        storage: 10Gi
    storageClassName: $STORAGE_CLASS
    volumeMode: Filesystem
EOF
  
  oc wait dv "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --for=condition=Ready --timeout=15m || {
    oc describe dv "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS"
    exit 1
  }
else
  oc annotate pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" \
    cdi.kubevirt.io/storage.bind.immediate.requested="true" --overwrite || true
  oc label pvc "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" \
    instancetype.kubevirt.io/default-instancetype=u1.medium \
    instancetype.kubevirt.io/default-preference=fedora --overwrite || true
fi

# Delete old DataImportCron if it exists
oc delete dataimportcron "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" --ignore-not-found || true

# Create DataImportCron with registry source (now that scratch space is configured)
# Note: DataImportCron requires registry source, not HTTP
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
          - ReadWriteOnce
        resources:
          requests:
            storage: 10Gi
        storageClassName: $STORAGE_CLASS
        volumeMode: Filesystem
EOF

# Wait for DataImportCron initial import
for i in {1..90}; do
  LATEST_DV=$(oc get dv -n "$IMAGE_NS" -o json | \
    jq -r ".items[] | select(.metadata.name | startswith(\"$GOLDEN_IMAGE_NAME-\")) | .metadata.name" | \
    sort -r | head -n 1)
  
  if [[ -n "$LATEST_DV" ]]; then
    DV_PHASE=$(oc get dv "$LATEST_DV" -n "$IMAGE_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    if [[ "$DV_PHASE" == "Succeeded" ]]; then
      break
    elif [[ "$DV_PHASE" =~ ^(Failed|Unknown)$ ]]; then
      oc describe dv "$LATEST_DV" -n "$IMAGE_NS"
      exit 1
    fi
  fi
  
  [[ $i -eq 90 ]] && exit 1
  sleep 10
done

# Wait for DataSource
for i in {1..30}; do
  DS_PVC=$(oc get datasource "$GOLDEN_IMAGE_NAME" -n "$IMAGE_NS" -o jsonpath='{.spec.source.pvc.name}' 2>/dev/null || echo "")
  if [[ -n "$DS_PVC" ]]; then
    PVC_PHASE=$(oc get pvc "$DS_PVC" -n "$IMAGE_NS" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    [[ "$PVC_PHASE" == "Bound" ]] && break
  fi
  [[ $i -eq 30 ]] && exit 1
  sleep 10
done

# Create RBAC
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

# Launch storage checkup job
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

# Wait for pod
MAX_WAIT=30
COUNTER=0
while true; do
  POD=$(oc get pod -n "$NAMESPACE" -l job-name=storage-checkup -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "$POD" ]]; then
    PHASE=$(oc get pod "$POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}')
    [[ "$PHASE" =~ ^(Running|Succeeded|Failed)$ ]] && break
  fi
  COUNTER=$((COUNTER + 1))
  [[ $COUNTER -ge $MAX_WAIT ]] && exit 1
  sleep 1
done

oc logs -f pod/"$POD" -n "$NAMESPACE" || true

SUCCEEDED=$(oc get configmap storage-checkup-config -n "$NAMESPACE" -o jsonpath='{.data.status\.succeeded}' 2>/dev/null || echo "false")
[[ "$SUCCEEDED" == "true" ]] && exit 0 || exit 1
