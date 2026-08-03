# Block replication with the VAST CSI Operator (OpenShift / OLM)

This example prepares a **two-site block replication** demo using VAST CSI Operator CRDs instead of a direct Helm `values.yaml` install.

- **Site 1 (primary):** StorageClass `vastdata-block` → subsystem `source`, secret `vast-mgmt`
- **Site 2 (destination):** StorageClass `vastdata-block2` → subsystem `destination`, secret `vast-mgmt2`

## Prerequisites

1. **VAST CSI Operator** installed in `vast-csi` (see [`../deploy/README.md`](../deploy/README.md)).
2. **Two VAST clusters** with replication peer configured between them.
   - Terraform reference: [`../../terraform-replication-setup/`](../../terraform-replication-setup/)
   - Lab Terraform: `demo/prerequisites/3-main.tf` (subsystems `source` / `destination`, VIP pool `gateway-1`).
3. **Block subsystems** on both clusters whose names match the `subsystem` fields in `02-vaststorage.yaml`.
4. Edit secret endpoints in `prerequisites/01-secrets.yaml` to fit your VAST clusters.

## Layout

| File | Purpose |
|------|---------|
| `prerequisites/01-secrets.yaml` | VMS credentials for site 1 (`vast-mgmt`) and site 2 (`vast-mgmt2`) |
| `01-vastcsidriver-block.yaml` | Block CSI driver + extensions / replication stack |
| `02-vaststorage.yaml` | Two `VastStorage` CRs → StorageClasses `vastdata-block` and `vastdata-block2` |
| `03-vast-storage-class-replication.yaml` | `VastStorageClassReplication` (primary + topology) |
| `04-pvc.yaml` | Sample PVCs on the primary StorageClass |
| `05-deploy.yaml` | Sample workload mounting one PVC |

For **per-volume** replication (single PVC), see [`../../operator-volume-replication/`](../../operator-volume-replication/).

## Install

```bash
# 1. VMS credentials (namespace must exist — created by operator install)
kubectl apply -f prerequisites/01-secrets.yaml

# 2. CSI driver with extensions
kubectl apply -f 01-vastcsidriver-block.yaml

# Wait until the driver and extension controller are ready
kubectl wait --for=condition=Available deployment -l app.kubernetes.io/name=vastcsi -n vast-csi --timeout=300s 2>/dev/null || true
kubectl get pods -n vast-csi
kubectl get pods -n csi-addons-system

# 3. StorageClasses (one per site)
kubectl apply -f 02-vaststorage.yaml
kubectl get storageclass vastdata-block vastdata-block2

# 4. Replication policy
kubectl apply -f 03-vast-storage-class-replication.yaml

# 5. Workload
kubectl apply -f 04-pvc.yaml
kubectl apply -f 05-deploy.yaml
```

## Verify

```bash
kubectl get vaststorageclassreplication -n default
kubectl get volumegroupreplication -A
kubectl get pvc
kubectl logs deploy/myapp
```
