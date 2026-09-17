# Replication examples (VAST CSI Operator)

Two-site storage-class replication demos using operator CRDs instead of a direct Helm `values.yaml` install.

| Folder | Driver | Description |
|--------|--------|-------------|
| [`block/`](block/README.md) | `block.csi.vastdata.com` | Block subsystems on two VAST clusters |
| [`nfs/`](nfs/README.md) | `csi.vastdata.com` | NFS root exports on two VAST clusters |

Each folder is self-contained. Apply manifests in numeric order (`00` … `06`). Step `01` is credentials (`VastCluster` for block, Secrets for NFS).

**Shared prerequisite:** VAST CSI Operator installed in `vast-csi` — see [`../deploy/README.md`](../deploy/README.md).

For **per-volume** replication (single PVC), see [`../../operator-volume-replication/`](../../operator-volume-replication/).
