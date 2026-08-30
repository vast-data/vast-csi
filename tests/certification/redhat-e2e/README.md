# Red Hat CSI Certification (Local OpenShift Suite)

This suite is intentionally isolated from normal pytest tests.
Run it explicitly as a standalone certification workflow.

It mirrors the Orion OpenShift operator certification flow under
`orion/pysrc/tests/csi/openshift/scripts/redhat-e2e/`.

## Suites

| Suite | Entry point | Output folder |
|-------|-------------|---------------|
| NFS CSI | `run_csi.py --profile nfs` | `output/nfs/<timestamp>/` |
| Block CSI | `run_csi.py --profile block` | `output/block/<timestamp>/` |
| KubeVirt | `run_kubevirt.py` | `output/kubevirt/<timestamp>/` |

Use the orchestrator to run one or all suites:

```bash
python3 tests/certification/redhat-e2e/run_certification.py nfs
python3 tests/certification/redhat-e2e/run_certification.py block
python3 tests/certification/redhat-e2e/run_certification.py kubevirt
python3 tests/certification/redhat-e2e/run_certification.py all
```

## What each suite does

### NFS / Block CSI

- Discovers OpenShift CSI tests for the VAST driver
- Runs a selected subset of OpenShift CSI tests locally
- Collects per-test logs and summary
- Archives the run output
- Ensures core CRs before test execution:
  - Installs VolumeSnapshot CRDs and snapshot-controller via `scripts/install_snapshot_crds.sh` when missing (shared by NFS, block, and KubeVirt)
  - NFS: `VastCluster` (`cluster`), `VastStorage` (`vastdata-filesystem`), `VastCSIDriver`
  - Block: `VastCluster` (`cluster-block`), `VastStorage` (`vastdata-block`), `VastCSIDriver` (`block.csi.vastdata.com`)
- NFS `VastStorage` sets `volumeNameFormat: csi:{id}` so CDI scratch PVCs avoid VAST quota name collisions (no runtime StorageClass patch)
- NFS view policy (`default` unless overridden): `nfs_root_squash=[]`, `nfs_no_squash=["*"]`, `use_auth_provider=false` so virt-launcher/CSI can chown on NFS
- NFS exports: `views.ensure_export(path="/", protocols=["NFS", "NFS4"])` so `vers=4.1` mounts work when the existing base view was NFS-only
- NFS trash folder: `clusters.ensure_trash_state(True)` so DeleteVolume uses Trash API (same as e2e `system` fixture)
- NFS `VastCSIDriver`: sets `deletionVipPool` / `deletionViewPolicy` (fallback when Trash API is unavailable)
- All profiles set `blockingClones: true` on `VastStorage` so volume clones wait for GSS completion before provisioning returns (NFS, block, and KubeVirt via shared `ensure_profile_stack()`)

### KubeVirt

- Runs the Red Hat-required KubeVirt storage checkup in Python via `run_kubevirt.py` and `kubevirt_checkup.py` (uses `tests/lib` `make_k8s`, namespaces, StorageClasses, and generic apply)
- Collects the checkup ConfigMap, logs, and cluster metadata
- Ensures the same VAST CR stack as NFS CSI via shared `ensure_profile_stack()` (whichever suite runs first creates `vastdata-filesystem`)
- **Golden image:** Fedora CoreOS qemu image via HTTP (15Gi PVC) plus DataImportCron. `cloneStrategy: snapshot` so CDI clones via CSI VolumeSnapshots.
- Makes `vastdata-filesystem` the unique default StorageClass and clears `storageclass.kubernetes.io/is-default-class` on every other class (CRC's `crc-csi-hostpath-provisioner` included).

## Run examples

NFS CSI:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile nfs --vast-endpoint <vast-mgmt-ip-or-fqdn>
```

Block CSI:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile block \
  --vast-endpoint <vast-mgmt-ip-or-fqdn>
```

Default VAST credentials are hardcoded as `admin` / `123456`.

KubeVirt on NFS (`vastdata-filesystem`):

```bash
python3 tests/certification/redhat-e2e/run_kubevirt.py
```

List-only mode for CSI:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile nfs --list-only
```

## Endpoint setup

Preferred:

```bash
export VAST_ENDPOINT=<vast-mgmt-ip-or-fqdn>
python3 tests/certification/redhat-e2e/run_certification.py nfs
```

Every run applies the CSI CR stack (`VastCluster` / `VastStorage` / `VastCSIDriver`). That path is idempotent and typically takes a few seconds.

## Manifests

- NFS: `manifest-nfs.yaml` (uses `vers=4.1` mount option)
- Block: `manifest-block.yaml`

## Output policy

Each profile keeps exactly one latest run under its own top folder:

- `tests/certification/redhat-e2e/output/nfs/<timestamp>/`
- `tests/certification/redhat-e2e/output/block/<timestamp>/`
- `tests/certification/redhat-e2e/output/kubevirt/<timestamp>/`

Archives:

- `tests/certification/redhat-e2e/output/nfs/<timestamp>.tar.gz`
- `tests/certification/redhat-e2e/output/block/<timestamp>.tar.gz`
- `tests/certification/redhat-e2e/output/kubevirt/<timestamp>.tar.gz`

When a new run starts for a profile, previous results in that profile folder are deleted.

## Prerequisites

- Docker logged in to `registry.redhat.io`
- Working `oc`/`kubectl` access to the OpenShift cluster
- VAST CSI operator installed and reachable from the cluster
- VolumeSnapshot CRDs: installed automatically during CR setup if the cluster does not already have them (CRC often does not)
- For NFS: trash folder enabled automatically; `deletionViewPolicy` / `deletionVipPool` set on `VastCSIDriver`
- For block: NVMe-oF subsystem `myblock` is created on the VAST cluster automatically via VMS API before applying CRs (see `tests/lib/constants.py`: `BLOCK_SUBSYSTEM`)
- For KubeVirt: nested virtualization or emulation enabled on the CRC host (`virtctl` is **not** required)

## KubeVirt helpers

- `python3 tests/certification/redhat-e2e/run_kubevirt.py` — NFS storage checkup (reuses a Bound golden image; does not re-download or re-convert)
- `python3 tests/certification/redhat-e2e/run_kubevirt.py --cleanup-first` — delete previous checkup job/VMs only; keeps the golden image
- `python3 tests/certification/redhat-e2e/run_kubevirt.py --reimport-golden-image` — force download/convert again
- `python3 tests/certification/redhat-e2e/cleanup_kubevirt.py` — delete checkup job/VMs and golden-image resources (add `--keep-golden-image` to keep the converted image)
- `python3 tests/certification/redhat-e2e/verify_golden_image.py` — verify DataSource, Bound PVC, and DataImportCron UpToDate
