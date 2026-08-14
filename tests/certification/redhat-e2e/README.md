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
- All profiles set `blockingClones: true` on `VastStorage` so volume clones wait for GSS completion before provisioning returns (NFS, block, and KubeVirt via shared `ensure_profile_stack()`)

### KubeVirt

- Runs the Red Hat-required KubeVirt storage checkup
- Uses the Orion scripts in `scripts/run-kubevirt.sh` and `scripts/run-kubevirt-block.sh`
- Collects the checkup ConfigMap, logs, and cluster metadata
- Ensures the same VAST CR stack as NFS CSI via shared `ensure_profile_stack()` (whichever suite runs first creates `vastdata-filesystem`)
- Block profile also ensures the block stack; NFS `vastdata-filesystem` is always ensured for CDI scratch space
- **Golden image:** Fedora CoreOS qemu image via HTTP (15Gi PVC) plus DataImportCron, same as the Orion `run-kubevirt.sh` that already passed certification. `cloneStrategy: copy`.

## Run examples

NFS CSI:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile nfs --vast-endpoint <vast-mgmt-ip-or-fqdn>
```

Block CSI:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile block \
  --vast-endpoint <vast-mgmt-ip-or-fqdn> \
  --vast-subsystem redhat-e2e-block
```

Default VAST credentials are hardcoded as `admin` / `123456`.

KubeVirt on NFS storage class:

```bash
python3 tests/certification/redhat-e2e/run_kubevirt.py --profile nfs
```

KubeVirt on block storage class:

```bash
python3 tests/certification/redhat-e2e/run_kubevirt.py --profile block
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

If CR setup is already done and should not be touched:

```bash
python3 tests/certification/redhat-e2e/run_csi.py --profile nfs --skip-ensure-csi-resources
```

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
- For block: NVMe-oF subsystem created on the VAST cluster (default name: `redhat-e2e-block`; the runner creates it automatically via VMS API before applying CRs)
- For KubeVirt: nested virtualization or emulation enabled on the CRC host (`virtctl` is **not** required)

## KubeVirt helper scripts

- `scripts/run-kubevirt.sh` - NFS/filesystem storage class checkup
- `scripts/run-kubevirt-block.sh` - block storage class checkup
- `scripts/cleanup-kubevirt.sh` - cleanup before retest
- `scripts/verify-golden-image.sh` - verify golden image discovery
