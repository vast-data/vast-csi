# Block replication with the VAST CSI Operator (OpenShift / OLM)

Two-site **block** replication demo using VAST CSI Operator CRDs.

- **Site 1 (primary):** StorageClass `vastdata-block` → subsystem `source`, VastCluster `vast-mgmt`
- **Site 2 (destination):** StorageClass `vastdata-block2` → subsystem `destination`, VastCluster `vast-mgmt2`

## Prerequisites

1. **VAST CSI Operator** installed in `vast-csi` (see [`../../deploy/README.md`](../../deploy/README.md)).
2. **Two VAST clusters** with replication peer configured between them.
   - Terraform reference: [`../../../terraform-replication-setup/`](../../../terraform-replication-setup/)
3. **Block subsystems** on both clusters whose names match the `subsystem` fields in `03-vaststorage.yaml`.
4. Edit VastCluster endpoints in `01-vastcluster.yaml` to fit your VAST clusters.

## Layout

| File | Purpose |
|------|---------|
| `00-vastextensionsmanager.yaml` | Cluster-wide extensions manager (singleton; install once per cluster) |
| `01-vastcluster.yaml` | VastCluster CRs for site 1 (`vast-mgmt`) and site 2 (`vast-mgmt2`); each creates a Secret |
| `02-vastcsidriver.yaml` | Block CSI driver + CSI-Addons sidecar registration |
| `03-vaststorage.yaml` | Two `VastStorage` CRs → StorageClasses `vastdata-block` and `vastdata-block2` |
| `04-vast-storage-class-replication.yaml` | `VastStorageClassReplication` (primary + topology) |
| `05-pvc.yaml` | Sample PVCs on the primary StorageClass |
| `06-deploy.yaml` | Sample workload mounting one PVC |

For **NFS** replication, see [`../nfs/README.md`](../nfs/README.md).

For **per-volume** replication (single PVC), see [`../../../operator-volume-replication/`](../../../operator-volume-replication/).

## Install

```bash
cd examples/csi-operator/replication/block

kubectl apply -f 01-vastcluster.yaml
kubectl apply -f 00-vastextensionsmanager.yaml
kubectl wait --for=condition=Available deployment/csi-addons-controller-manager -n vast-csi --timeout=300s
kubectl wait --for=condition=Available deployment -l app.kubernetes.io/component=vast-extensions-manager -n vast-csi --timeout=300s

kubectl apply -f 02-vastcsidriver.yaml
kubectl wait --for=condition=Available deployment -l app.kubernetes.io/name=vastcsi -n vast-csi --timeout=300s 2>/dev/null || true

kubectl apply -f 03-vaststorage.yaml
kubectl apply -f 04-vast-storage-class-replication.yaml
kubectl apply -f 05-pvc.yaml
kubectl apply -f 06-deploy.yaml
```

## Verify

```bash
kubectl get vastextensionsmanager -n vast-csi
kubectl get vaststorageclassreplication -n default
kubectl get volumegroupreplication -A
kubectl get pvc
kubectl logs deploy/myapp-block
```
