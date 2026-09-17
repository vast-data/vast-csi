# NFS replication with the VAST CSI Operator (OpenShift / OLM)

Two-site **NFS** replication demo using VAST CSI Operator CRDs.

- **Site 1 (primary):** StorageClass `vastdata-filesystem` → root export `/k8s`, secret `vast-mgmt`
- **Site 2 (destination):** StorageClass `vastdata-filesystem2` → root export `/k8s-repl`, secret `vast-mgmt2`

## Prerequisites

1. **VAST CSI Operator** installed in `vast-csi` (see [`../../deploy/README.md`](../../deploy/README.md)).
2. **Two VAST clusters** with replication peer configured between them.
   - Terraform reference: [`../../../terraform-replication-setup/`](../../../terraform-replication-setup/)
3. **NFS root exports** on both clusters matching the `storagePath` fields in `03-vaststorage.yaml`.
4. Edit secret endpoints in `01-secrets.yaml` to fit your VAST clusters.

## Layout

| File | Purpose |
|------|---------|
| `00-vastextensionsmanager.yaml` | Cluster-wide extensions manager (singleton; install once per cluster) |
| `01-secrets.yaml` | VMS credentials for site 1 (`vast-mgmt`) and site 2 (`vast-mgmt2`) |
| `02-vastcsidriver.yaml` | NFS CSI driver + CSI-Addons sidecar registration |
| `03-vaststorage.yaml` | Two `VastStorage` CRs → StorageClasses `vastdata-filesystem` and `vastdata-filesystem2` |
| `04-vast-storage-class-replication.yaml` | `VastStorageClassReplication` (primary + topology) |
| `05-pvc.yaml` | Sample PVCs on the primary StorageClass |
| `06-deploy.yaml` | Sample workload mounting one PVC |

For **block** replication, see [`../block/README.md`](../block/README.md).

For **per-volume** replication (single PVC), see [`../../../operator-volume-replication/`](../../../operator-volume-replication/).

## Install

```bash
cd examples/csi-operator/replication/nfs

kubectl apply -f 01-secrets.yaml
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
kubectl logs deploy/myapp-nfs
```
