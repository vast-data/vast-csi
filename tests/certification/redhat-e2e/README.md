# Red Hat CSI Certification (Local OpenShift Suite)

This suite is intentionally isolated from normal pytest tests.
Run it explicitly as a standalone certification workflow.

**Single entry point:** `run_certification.py` — run **one** suite at a time (`nfs`, `block`, or `kubevirt`).

## Suites

| Suite | Command | Output folder |
|-------|---------|---------------|
| NFS CSI | `run_certification.py nfs` | `output/nfs/<timestamp>/` |
| Block CSI | `run_certification.py block` | `output/block/<timestamp>/` |
| KubeVirt | `run_certification.py kubevirt` | `output/kubevirt/<timestamp>/` |

```bash
python3 tests/certification/redhat-e2e/run_certification.py nfs --vast-endpoint <vast-mgmt>
python3 tests/certification/redhat-e2e/run_certification.py block --vast-endpoint <vast-mgmt>
python3 tests/certification/redhat-e2e/run_certification.py kubevirt --vast-endpoint <vast-mgmt>
```

Or via Make:

```bash
make -C tests cert-nfs VAST_ENDPOINT=<vast-mgmt>
make -C tests cert-block VAST_ENDPOINT=<vast-mgmt>
make -C tests cert-kubevirt VAST_ENDPOINT=<vast-mgmt>
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
- Block sets `allowROManyBlockFsMode: true` on `VastCSIDriver` so ReadOnlyMany block filesystem mounts are enforced read-only at the OS level

### KubeVirt

- Runs the Red Hat-required KubeVirt storage checkup (`kubevirt_checkup.py`)
- Collects the checkup ConfigMap, logs, and cluster metadata
- Ensures the same VAST CR stack as NFS CSI via shared `ensure_profile_stack()`
- **Golden image:** Alpine (or configured) image via HTTP plus DataImportCron. `cloneStrategy: snapshot` so CDI clones via CSI VolumeSnapshots.
- Makes `vastdata-filesystem` the unique default StorageClass and clears `storageclass.kubernetes.io/is-default-class` on every other class

## Useful flags

```bash
# CSI: list selected tests without running
python3 tests/certification/redhat-e2e/run_certification.py nfs --list-only --vast-endpoint <vast-mgmt>

# KubeVirt: cleanup previous job/VMs (keeps golden image)
python3 tests/certification/redhat-e2e/run_certification.py kubevirt --cleanup-first --vast-endpoint <vast-mgmt>

# KubeVirt: force golden-image reimport
python3 tests/certification/redhat-e2e/run_certification.py kubevirt --reimport-golden-image --vast-endpoint <vast-mgmt>
```

Default VAST credentials are `admin` / `123456`.

Preferred endpoint setup:

```bash
export VAST_ENDPOINT=<vast-mgmt-ip-or-fqdn>
python3 tests/certification/redhat-e2e/run_certification.py nfs
```

Every run applies the CSI CR stack (`VastCluster` / `VastStorage` / `VastCSIDriver`). That path is idempotent and typically takes a few seconds.

## Manifests

- NFS: `manifest-nfs.yaml` (uses `vers=4.1` mount option; `capReadOnlyMany: true` for ROX snapshot restore)
- Block: `manifest-block.yaml` (ext3/ext4/xfs; CSI EV; snapshot/clone/expansion/ROX enabled; `allowROManyBlockFsMode`)

### Tests that cannot be enabled via external YAML

OpenShift’s external storage harness hard-skips these regardless of driver support:

- **Block multi-PV same storage (block volmode)** — upstream skip for raw block mode
- **Pre-provisioned PV** — external YAML driver definition has no PreprovisionedPV API
- **Inline-volume (*)** — in-tree `InlineVolume` VolType; not the same as CSI EV. Use **CSI Ephemeral-volume** instead (enabled via `InlineVolumes` in the manifest)
- **NFS Dynamic Snapshot × ephemeral / Ephemeral Snapshot × persistent** — framework pattern mismatches (matching variants already run)

The cert runner filters unenableable patterns out of block selection so they do not appear as `skipped` in `summary.json`.

CSI InlineVolumes require `VastCSIDriver.spec.secretName` (wired automatically to the VastCluster secret); the OpenShift suite cannot pass `nodePublishSecretRef` in the manifest.

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

## Layout

| File | Role |
|------|------|
| `run_certification.py` | **Only** CLI entry point |
| `csi_runner.py` | Shared NFS/block CSI suite logic |
| `kubevirt_checkup.py` | KubeVirt storage checkup implementation |
| `manifest-*.yaml` | OpenShift external-storage driver definitions |
