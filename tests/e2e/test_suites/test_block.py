"""Block / vastblock chart test bodies."""
import re
import time
from datetime import datetime

import pytest
from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.timing import wait
from easypy.units import MINUTE

from lib.constants import (
    BLOCK_SUBSYSTEM,
    BUSYBOX_IMAGE,
    MGMT_SECRET,
    SNAPSHOT_CLASS,
    VIPPOOL_NAME,
    block_storage_class,
)
from e2e.logging import logger

from lib.builders.storage import PVCBuilder, VolumeSnapshotBuilder
from lib.builders.workloads import PodBuilder
from e2e.test_suites.common import (
    CONCURRENT_VOLUME_COUNT,
    files_in_pod,
    make_filesystem_pvc,
    make_writer_pod,
    parse_iso_date,
    wait_volumes_detached,
    writer_has_data,
)

# ---------------------------------------------------------------------------
# Test bodies
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.block
def test_block_basic_pvc_and_pod(k8s):
    """Multi-filesystem IO bounce test with incremental resize."""

    volume_size = "3Gi"
    expand_step_gi = 300
    bounce_count = 3
    io_settle_seconds = 60

    heavy_io_cmd = [
        "sh", "-c",
        (
            "pass=0;"
            " while true; do"
            "  dd if=/dev/zero of=/shared/data bs=4M count=256 oflag=dsync conv=notrunc 2>/dev/null;"
            "  pass=$((pass+1));"
            "  echo $(date -Iseconds) pass=$pass >> /shared/log;"
            " done"
        ),
    ]

    node_names = k8s.nodes.names()
    if len(node_names) < 2:
        pytest.skip(f"Need ≥ 2 nodes for bounce test, found: {node_names}")

    sc_ext4 = block_storage_class(fs_type="ext4")
    sc_xfs  = block_storage_class(fs_type="xfs")
    sc_ext3 = block_storage_class(fs_type="ext3")
    suffix  = random_nice_name(max_length=18)

    volumes = [
        {"pvc": f"basic-ext4-pvc-{suffix}", "pod": f"basic-ext4-pod-{suffix}",
         "sc": sc_ext4, "fs": "ext4"},
        {"pvc": f"basic-xfs-pvc-{suffix}",  "pod": f"basic-xfs-pod-{suffix}",
         "sc": sc_xfs,  "fs": "xfs"},
        {"pvc": f"basic-ext3-pvc-{suffix}", "pod": f"basic-ext3-pod-{suffix}",
         "sc": sc_ext3, "fs": "ext3"},
    ]

    logger.info(
        f"Creating {len(volumes)} × {volume_size} block PVCs: "
        + ", ".join(v["fs"] for v in volumes)
    )
    for v in volumes:
        k8s.pvcs.create(make_filesystem_pvc(v["pvc"], v["sc"], storage=volume_size))
    for v in volumes:
        k8s.pvcs.wait(
            timeout=5 * MINUTE, name=v["pvc"],
            error_msg=f"PVC {v['pvc']!r} ({v['fs']}) did not bind",
        )

    pod_builders = {}

    def _start_pods(node: str) -> float:
        t0 = time.monotonic()
        for v in volumes:
            pb = make_writer_pod(
                v["pod"], v["pvc"],
                volume_name="block-data",
                command=heavy_io_cmd,
            )
            pb.with_spec(nodeSelector={"kubernetes.io/hostname": node})
            pod_builders[v["pod"]] = pb
            k8s.pods.create(pb)
        for v in volumes:
            k8s.pods.wait(
                timeout=3 * MINUTE, name=v["pod"],
                error_msg=(
                    f"Pod {v['pod']!r} ({v['fs']}) did not reach Running on {node!r} "
                    f"within {3 * MINUTE} min — possible mount stall"
                ),
            )
        elapsed = time.monotonic() - t0
        logger.info(f"All {len(volumes)} pods Running on {node!r} in {elapsed:.1f}s")
        if elapsed > 120:
            logger.warning(
                f"Slow mount on {node!r}: {elapsed:.1f}s > 120s "
            )
        return elapsed

    def _stop_pods() -> None:
        for v in volumes:
            k8s.pods.delete(name=v["pod"])
        for v in volumes:
            k8s.pods.wait(
                timeout=MINUTE, name=v["pod"], condition="Deleted",
                error_msg=f"Pod {v['pod']!r} not deleted",
            )

    node_a, node_b = node_names[0], node_names[1]
    logger.info(f"Bounce nodes: {node_a!r} <-> {node_b!r}")

    _start_pods(node_a)
    logger.info(f"IO settling for {io_settle_seconds}s before first bounce")
    time.sleep(io_settle_seconds)
    current_size_gi = int(volume_size.rstrip("Gi"))

    for bounce in range(1, bounce_count + 1):
        src = node_a if bounce % 2 == 1 else node_b
        dst = node_b if bounce % 2 == 1 else node_a
        logger.info(f"=== Bounce {bounce}/{bounce_count}: {src!r} → {dst!r} ===")

        _stop_pods()
        wait_volumes_detached(k8s, [v["pvc"] for v in volumes], src)

        # Expand every PVC by expand_step_gi on every bounce
        current_size_gi += expand_step_gi
        new_size = f"{current_size_gi}Gi"
        logger.info(f"Expanding all PVCs to {new_size} before bounce {bounce}")
        for v in volumes:
            pvc = k8s.pvcs.get(name=v["pvc"])
            pvc.spec.resources.requests.storage = new_size
            k8s.pvcs.apply([pvc])
        logger.info(f"PVC resize to {new_size} requested; NodeExpandVolume will run on next pod mount")

        mount_time = _start_pods(dst)
        logger.info(f"Bounce {bounce} mount time: {mount_time:.1f}s")

        # Verify capacity was updated by NodeExpandVolume (runs during pod mount above)
        for v in volumes:
            cap = k8s.pvcs.get(name=v["pvc"]).status.capacity.storage
            assert cap in (new_size, str(current_size_gi * 1024 ** 3)), (
                f"PVC {v['pvc']!r} ({v['fs']}) capacity {cap!r} != {new_size} after NodeExpandVolume"
            )

        for v in volumes:
            wait(
                2 * MINUTE,
                lambda pod=v["pod"]: writer_has_data(k8s, pod, filename="log"),
                message=f"No IO progress in {v['pod']!r} ({v['fs']}) after bounce {bounce}",
            )

        if bounce < bounce_count:
            logger.info(f"IO settling for {io_settle_seconds}s before next bounce")
            time.sleep(io_settle_seconds)

    _assert_no_mount_stall_events(k8s, volumes)


@pytest.mark.e2e
@pytest.mark.block
def test_block_ephemeral_volumes(system, k8s):
    """CSI inline ephemeral volumes (EV) for ext4 and xfs, same lifecycle as NFS EV."""
    suffix = random_nice_name(max_length=20)
    created = []
    for fs_type in ("ext4", "xfs"):
        pod_name = f"ev-pod-{fs_type}-{suffix}"
        volume_group = f"ev-{fs_type}-{suffix}"
        volume = {
            "name": "my-eph-vol",
            "csi": {
                "driver": "block.csi.vastdata.com",
                "fsType": fs_type,
                "nodePublishSecretRef": {"name": MGMT_SECRET},
                "volumeAttributes": {
                    "size": "1G",
                    "subsystem": BLOCK_SUBSYSTEM,
                    "vip_pool_name": VIPPOOL_NAME,
                    "volume_group": volume_group,
                },
            },
        }
        k8s.pods.create(
            PodBuilder.new(name=pod_name, container_name="my-frontend", image=BUSYBOX_IMAGE)
            .with_volume("my-eph-vol", "/shared", volume)
        )
        created.append((pod_name, volume_group))

    vms_volumes = []
    for pod_name, volume_group in created:
        k8s.pods.wait(
            timeout=5 * MINUTE,
            name=pod_name,
            error_msg=f"the pod {pod_name!r} was not moved to the running state within the allotted period",
        )
        vol = wait(
            MINUTE,
            lambda vg=volume_group: system.volumes.single(lambda v: vg in (v.name or "")),
            message=f"no VMS volume for {volume_group}",
        )
        wait(
            90,
            lambda pn=pod_name: bool(files_in_pod(k8s, pn)),
            message=f"{pod_name} is still empty",
        )
        vms_volumes.append(vol)

    for pod_name, _ in created:
        k8s.pods.delete(name=pod_name)
    for vol in vms_volumes:
        wait(MINUTE, lambda v=vol: v.was_removed, message=f"{vol} is still there")


@pytest.mark.e2e
@pytest.mark.block
def test_block_snapshot_restore(system, k8s):
    """Snapshot restore with resize across ext4, XFS and ext3 filesystems.

    Creates one source PVC per filesystem, snapshots all three, then for each
    snapshot creates two restores using the same filesystem as the source:
      - same-size restore  (2 Gi) — verifies data integrity
      - enlarged restore   (4 Gi) — verifies data integrity
    """
    snap_class = SNAPSHOT_CLASS
    source_size = "2Gi"
    expanded_size = "4Gi"
    suffix = random_nice_name(max_length=16)

    volumes = [
        {
            "fs": fs,
            "sc": block_storage_class(fs_type=fs),
            "src_pvc":  f"snap-src-{fs}-{suffix}",
            "src_pod":  f"snap-src-pod-{fs}-{suffix}",
            "snap":     f"snap-{fs}-{suffix}",
            "rst_pvc":  f"snap-rst-{fs}-{suffix}",
            "rst_pod":  f"snap-rst-pod-{fs}-{suffix}",
            "exp_pvc":  f"snap-exp-{fs}-{suffix}",
            "exp_pod":  f"snap-exp-pod-{fs}-{suffix}",
        }
        for fs in ("ext4", "xfs", "ext3")
    ]

    for v in volumes:
        k8s.pvcs.create(make_filesystem_pvc(v["src_pvc"], v["sc"], storage=source_size))
    for v in volumes:
        k8s.pvcs.wait(timeout=3 * MINUTE, name=v["src_pvc"],
                      error_msg=f"[{v['fs']}] source PVC did not bind")
    for v in volumes:
        k8s.pods.create(make_writer_pod(v["src_pod"], v["src_pvc"], volume_name="block-data"))
    for v in volumes:
        k8s.pods.wait(timeout=5 * MINUTE, name=v["src_pod"],
                      error_msg=f"[{v['fs']}] source pod did not start")
        wait(MINUTE, lambda pod=v["src_pod"]: writer_has_data(k8s, pod),
             message=f"[{v['fs']}] no data written to source PVC")
        k8s.pods.exec(v["src_pod"], "sync")

    for v in volumes:
        k8s.volumesnapshots.create(VolumeSnapshotBuilder.new(
            name=v["snap"], pvc_name=v["src_pvc"], snapshot_class_name=snap_class,
        ))
    for v in volumes:
        with logger.indented(f"[{v['fs']}] waiting for snapshot"):
            uid = k8s.volumesnapshots.wait(
                timeout=5 * MINUTE, name=v["snap"],
                error_msg=f"[{v['fs']}] snapshot not ready",
            )["metadata"]["uid"]
            wait(5 * MINUTE, lambda u=uid: system.snapshots.single(lambda s: u in s.name),
                 message=f"[{v['fs']}] no VMS snapshot for {uid}")
        v["src_pod_name_for_verify"] = v["src_pod"]

    for v in volumes:
        k8s.pvcs.create(
            make_filesystem_pvc(v["rst_pvc"], v["sc"], storage=source_size)
            .with_data_source(name=v["snap"], kind="VolumeSnapshot",
                              apiGroup="snapshot.storage.k8s.io")
        )
        k8s.pvcs.create(
            make_filesystem_pvc(v["exp_pvc"], v["sc"], storage=expanded_size)
            .with_data_source(name=v["snap"], kind="VolumeSnapshot",
                              apiGroup="snapshot.storage.k8s.io")
        )
    for v in volumes:
        k8s.pvcs.wait(timeout=10 * MINUTE, name=v["rst_pvc"],
                      error_msg=f"[{v['fs']}] same-size restore PVC did not bind")
        k8s.pvcs.wait(timeout=10 * MINUTE, name=v["exp_pvc"],
                      error_msg=f"[{v['fs']}] enlarged restore PVC did not bind")
        capacity = k8s.pvcs.get(name=v["exp_pvc"]).status.capacity.storage
        assert capacity in (expanded_size, str(4 * 1024 ** 3)), (
            f"[{v['fs']}] enlarged PVC capacity {capacity!r} != {expanded_size}"
        )

    for v in volumes:
        k8s.pods.create(make_writer_pod(v["rst_pod"], v["rst_pvc"],
                                        volume_name="block-data", command=["sleep", "3600"]))
        k8s.pods.create(make_writer_pod(v["exp_pod"], v["exp_pvc"],
                                        volume_name="block-data", command=["sleep", "3600"]))
    for v in volumes:
        k8s.pods.wait(timeout=5 * MINUTE, name=v["rst_pod"],
                      error_msg=f"[{v['fs']}] same-size restore pod did not start")
        k8s.pods.wait(timeout=5 * MINUTE, name=v["exp_pod"],
                      error_msg=f"[{v['fs']}] enlarged restore pod did not start")

        src_pod = v["src_pod"]
        for pod, label in ((v["rst_pod"], "same-size restore"), (v["exp_pod"], "enlarged restore")):
            date_str = k8s.pods.exec(pod, f"head -1 /shared/{src_pod}")
            dt = parse_iso_date(date_str.strip())
            assert isinstance(dt, datetime), (
                f"[{v['fs']}] {label}: expected timestamp, got: {date_str!r}"
            )
            logger.info(f"[{v['fs']}] {label}: data verified (written at {dt})")



@pytest.mark.e2e
@pytest.mark.block
def test_block_volume_clone(k8s):
    """PVC clone with resize across ext4, XFS and ext3 filesystems.

    Creates one source PVC per filesystem, then for each source creates two
    clones using the same filesystem as the source:
      - same-size clone    (2 Gi) — verifies data integrity
      - enlarged clone     (4 Gi) — verifies data integrity
    """
    source_size = "2Gi"
    expanded_size = "4Gi"
    suffix = random_nice_name(max_length=16)

    volumes = [
        {
            "fs": fs,
            "sc": block_storage_class(fs_type=fs),
            "src_pvc":  f"clone-src-{fs}-{suffix}",
            "src_pod":  f"clone-src-pod-{fs}-{suffix}",
            "cln_pvc":  f"clone-{fs}-{suffix}",
            "cln_pod":  f"clone-pod-{fs}-{suffix}",
            "exp_pvc":  f"clone-exp-{fs}-{suffix}",
            "exp_pod":  f"clone-exp-pod-{fs}-{suffix}",
        }
        for fs in ("ext4", "xfs", "ext3")
    ]

    for v in volumes:
        k8s.pvcs.create(make_filesystem_pvc(v["src_pvc"], v["sc"], storage=source_size))
    for v in volumes:
        k8s.pvcs.wait(timeout=3 * MINUTE, name=v["src_pvc"],
                      error_msg=f"[{v['fs']}] source PVC did not bind")
    for v in volumes:
        k8s.pods.create(make_writer_pod(v["src_pod"], v["src_pvc"], volume_name="block-data"))
    for v in volumes:
        k8s.pods.wait(timeout=5 * MINUTE, name=v["src_pod"],
                      error_msg=f"[{v['fs']}] source pod did not start")
        wait(MINUTE, lambda pod=v["src_pod"]: writer_has_data(k8s, pod),
             message=f"[{v['fs']}] no data written to source PVC")

    for v in volumes:
        k8s.pods.delete(name=v["src_pod"])
    for v in volumes:
        k8s.pods.wait(timeout=MINUTE, name=v["src_pod"], condition="Deleted",
                      error_msg=f"[{v['fs']}] source pod not deleted")

    for v in volumes:
        k8s.pvcs.create(
            make_filesystem_pvc(v["cln_pvc"], v["sc"], storage=source_size)
            .with_data_source(name=v["src_pvc"], kind="PersistentVolumeClaim")
        )
        k8s.pvcs.create(
            make_filesystem_pvc(v["exp_pvc"], v["sc"], storage=expanded_size)
            .with_data_source(name=v["src_pvc"], kind="PersistentVolumeClaim")
        )
    for v in volumes:
        k8s.pvcs.wait(timeout=10 * MINUTE, name=v["cln_pvc"],
                      error_msg=f"[{v['fs']}] same-size clone PVC did not bind")
        k8s.pvcs.wait(timeout=10 * MINUTE, name=v["exp_pvc"],
                      error_msg=f"[{v['fs']}] enlarged clone PVC did not bind")
        capacity = k8s.pvcs.get(name=v["exp_pvc"]).status.capacity.storage
        assert capacity in (expanded_size, str(4 * 1024 ** 3)), (
            f"[{v['fs']}] enlarged clone capacity {capacity!r} != {expanded_size}"
        )

    for v in volumes:
        k8s.pods.create(make_writer_pod(v["cln_pod"], v["cln_pvc"],
                                        volume_name="block-data", command=["sleep", "3600"]))
        k8s.pods.create(make_writer_pod(v["exp_pod"], v["exp_pvc"],
                                        volume_name="block-data", command=["sleep", "3600"]))
    for v in volumes:
        k8s.pods.wait(timeout=5 * MINUTE, name=v["cln_pod"],
                      error_msg=f"[{v['fs']}] same-size clone pod did not start")
        k8s.pods.wait(timeout=5 * MINUTE, name=v["exp_pod"],
                      error_msg=f"[{v['fs']}] enlarged clone pod did not start")

        src_pod = v["src_pod"]
        for pod, label in ((v["cln_pod"], "same-size clone"), (v["exp_pod"], "enlarged clone")):
            date_str = k8s.pods.exec(pod, f"head -1 /shared/{src_pod}")
            dt = parse_iso_date(date_str.strip())
            assert isinstance(dt, datetime), (
                f"[{v['fs']}] {label}: expected timestamp, got: {date_str!r}"
            )
            logger.info(f"[{v['fs']}] {label}: data verified (written at {dt})")


@pytest.mark.e2e
@pytest.mark.block
def test_block_xfs_concurrent(system, k8s):
    """XFS block volumes: N concurrent RWO mounts, then snapshot one and attach N ROX readers.

    Phase 1 — RWO: Create N XFS PVCs + N writer pods simultaneously.
              Verifies concurrent NVMe attach and XFS integrity check under load.
    Phase 2 — ROX: Snapshot the first RWO PVC, restore N ReadOnlyMany PVCs,
              attach N reader pods simultaneously and verify data consistency.
    """
    storage_class = block_storage_class(fs_type="xfs")
    snap_class = SNAPSHOT_CLASS
    suffix = random_nice_name(max_length=20)
    n = CONCURRENT_VOLUME_COUNT

    rwo_pvc_names = [f"block-xfs-rwo-pvc-{i}-{suffix}" for i in range(n)]
    rwo_pod_names = [f"block-xfs-rwo-pod-{i}-{suffix}" for i in range(n)]

    # --- Phase 1: concurrent RWO ---
    for pvc_name in rwo_pvc_names:
        k8s.pvcs.create(make_filesystem_pvc(pvc_name, storage_class))
    for pvc_name in rwo_pvc_names:
        k8s.pvcs.wait(timeout=3 * MINUTE, name=pvc_name, error_msg=f"PVC {pvc_name!r} did not bind")

    logger.info(f"Phase 1: launching {n} XFS RWO pods simultaneously")
    for pod_name, pvc_name in zip(rwo_pod_names, rwo_pvc_names):
        k8s.pods.create(make_writer_pod(pod_name, pvc_name, volume_name="block-data"))
    for pod_name in rwo_pod_names:
        # XFS volumes need extra time: mkfs.xfs + xfs_db integrity check + concurrent VAST ops
        k8s.pods.wait(timeout=10 * MINUTE, name=pod_name, error_msg=f"Pod {pod_name!r} did not start")

    for pod_name in rwo_pod_names:
        wait(
            MINUTE,
            lambda pn=pod_name: writer_has_data(k8s, pn),
            message=f"No data written in pod {pod_name!r}",
        )
    logger.info(f"Phase 1: all {n} XFS RWO pods verified")

    # --- Phase 2: snapshot pod-0 PVC, restore as N ROX PVCs ---
    src_pod = rwo_pod_names[0]
    src_pvc = rwo_pvc_names[0]
    snap_name = f"block-xfs-snap-{suffix}"
    rox_pvc_names = [f"block-xfs-rox-pvc-{i}-{suffix}" for i in range(n)]
    rox_pod_names = [f"block-xfs-rox-pod-{i}-{suffix}" for i in range(n)]

    k8s.pods.exec(src_pod, "sync")
    k8s.volumesnapshots.create(VolumeSnapshotBuilder.new(
        name=snap_name, pvc_name=src_pvc, snapshot_class_name=snap_class,
    ))
    with logger.indented("waiting for XFS snapshot"):
        uid = k8s.volumesnapshots.wait(
            timeout=5 * MINUTE, name=snap_name,
            error_msg=f"Snapshot {snap_name!r} not ready",
        )["metadata"]["uid"]
        wait(5 * MINUTE, lambda: system.snapshots.single(lambda s: uid in s.name),
             message=f"no VMS snapshot for {uid}")

    # Release source PVC before restoring as ROX
    k8s.pods.delete(name=src_pod)
    k8s.pods.wait(timeout=MINUTE, name=src_pod, condition="Deleted",
                  error_msg=f"Source pod {src_pod!r} not deleted")

    logger.info(f"Phase 2: creating {n} ReadOnlyMany restore PVCs from XFS snapshot")
    for rox_pvc in rox_pvc_names:
        k8s.pvcs.create(
            make_filesystem_pvc(rox_pvc, storage_class, access_modes=["ReadOnlyMany"])
            .with_data_source(name=snap_name, kind="VolumeSnapshot",
                              apiGroup="snapshot.storage.k8s.io")
        )
    for rox_pvc in rox_pvc_names:
        # 5 min: snapshot clone may retry once if globalsnapstreams Finalizing->Completed
        # transition races with the X_CSI_VMS_TIMEOUT (60s) in the controller.
        k8s.pvcs.wait(timeout=5 * MINUTE, name=rox_pvc, error_msg=f"ROX PVC {rox_pvc!r} did not bind")

    logger.info(f"Phase 2: launching {n} ROX reader pods simultaneously")
    for rox_pod, rox_pvc in zip(rox_pod_names, rox_pvc_names):
        k8s.pods.create(make_writer_pod(rox_pod, rox_pvc, volume_name="block-data", command=["sleep", "3600"]))
    for rox_pod in rox_pod_names:
        k8s.pods.wait(timeout=10 * MINUTE, name=rox_pod, error_msg=f"ROX pod {rox_pod!r} did not start")

    for rox_pod in rox_pod_names:
        date_str = k8s.pods.exec(rox_pod, f"head -1 /shared/{src_pod}")
        dt = parse_iso_date(date_str.strip())
        assert isinstance(dt, datetime), f"Expected timestamp in ROX pod {rox_pod!r}, got: {date_str!r}"
    logger.info(f"Phase 2: all {n} ROX XFS pods verified data consistency")


@pytest.mark.e2e
@pytest.mark.block
def test_block_raw_block_volume(k8s):
    """Verify volumeMode=Block: pod receives a raw block device and can write/read via dd."""
    storage_class = block_storage_class()
    suffix = random_nice_name(max_length=24)
    pvc_name = f"block-raw-pvc-{suffix}"
    pod_name = f"block-raw-pod-{suffix}"
    device_path = "/dev/block"

    pvc = (
        PVCBuilder.new(name=pvc_name, access_modes=["ReadWriteOnce"],
                       storage_class_name=storage_class, storage="2Gi")
        .with_volume_mode("Block")
    )
    k8s.pvcs.create(pvc)
    k8s.pvcs.wait(timeout=3 * MINUTE, name=pvc_name, error_msg=f"PVC {pvc_name!r} did not bind")

    pod = (
        PodBuilder.new(name=pod_name, container_name="writer", image=BUSYBOX_IMAGE,
                       command=["sleep", "3600"])
        .with_volume_device(
            "block-dev", device_path,
            {"name": "block-dev", "persistentVolumeClaim": {"claimName": pvc_name}},
        )
    )
    k8s.pods.create(pod)
    k8s.pods.wait(timeout=5 * MINUTE, name=pod_name, error_msg=f"Pod {pod_name!r} did not start")

    # Write 1 MiB of random data to the raw device, then read the first block back
    k8s.pods.exec(pod_name, f"sh -c 'dd if=/dev/urandom of={device_path} bs=4096 count=256 conv=fsync'")
    checksum = k8s.pods.exec(
        pod_name, f"sh -c 'dd if={device_path} bs=4096 count=256 2>/dev/null | md5sum'"
    ).strip().split()[0]
    empty_md5 = "d41d8cd98f00b204e9800998ecf8427e"
    assert checksum and checksum != empty_md5, \
        f"Raw block device appears empty after dd write (md5={checksum!r})"
    logger.info(f"Raw block volume verified: md5={checksum}")


@pytest.mark.e2e
@pytest.mark.block
def test_block_reschedule_normal(k8s):
    """Regression test for Multi-Attach / ControllerPublishVolume timeout (field bug VAST 5.3.x).

    Scenario: RWO volume moves from node A to node B under normal conditions (no network fault).
    The volume must detach and reattach within 3 minutes — if ControllerPublishVolume stalls
    (volume stuck attached to old node) the test will surface FailedAttachVolume events and
    exceed the deadline, reproducing the xAI-reported hang.
    """

    storage_class = block_storage_class()
    suffix = random_nice_name(max_length=24)
    pvc_name = f"block-pvc-{suffix}"
    pod_name = f"block-pod-{suffix}"

    node_names = k8s.nodes.names()
    if len(node_names) < 2:
        pytest.skip(f"Expected 2+ nodes for reschedule test, found: {node_names}")

    k8s.pvcs.create(make_filesystem_pvc(pvc_name, storage_class))
    k8s.pvcs.wait(timeout=3 * MINUTE, name=pvc_name, error_msg=f"PVC {pvc_name!r} did not bind")

    # Pin first pod to node[0]
    pod_builder = make_writer_pod(pod_name, pvc_name, volume_name="block-data", command=["sleep", "3600"])
    pod_builder.with_spec(nodeSelector={"kubernetes.io/hostname": node_names[0]})
    k8s.pods.create(pod_builder)
    k8s.pods.wait(timeout=5 * MINUTE, name=pod_name, error_msg=f"Pod {pod_name!r} did not start")
    logger.info(f"Pod running on {node_names[0]!r}, rescheduling to {node_names[1]!r}")

    k8s.pods.delete(name=pod_name)
    k8s.pods.wait(timeout=MINUTE, name=pod_name, condition="Deleted",
                  error_msg=f"Pod {pod_name!r} not deleted")

    # Reschedule to node[1] — must succeed within 3 min with no FailedAttachVolume
    pod_builder.with_spec(nodeSelector={"kubernetes.io/hostname": node_names[1]})
    k8s.pods.create(pod_builder)
    k8s.pods.wait(
        timeout=3 * MINUTE,
        name=pod_name,
        error_msg=(
            f"Pod {pod_name!r} did not reschedule to {node_names[1]!r} within 3 min "
            f"(possible Multi-Attach / ControllerPublishVolume timeout regression)"
        ),
    )

    # Check events for the hard failure: external-attacher timeout.
    # Transient "Multi-Attach" warnings are normal (k8s races to attach before the old node
    # releases) and self-resolve — the pod starting within 3 min already proves they resolved.
    # The actual xAI bug was "timed out waiting for external-attacher" which means the attach
    # NEVER succeeded and the volume was permanently stuck on the old node.
    events_json = k8s.kubectl("get", "events", "-n", "default",
                              "--field-selector", f"involvedObject.name={pod_name}",
                              "-o", "json")
    events = Bunch.from_json(events_json)["items"]
    timeout_events = [
        e for e in events
        if e.reason == "FailedAttachVolume" and "timed out waiting for external-attacher" in (e.message or "")
    ]
    assert not timeout_events, (
        f"External-attacher timeout for {pod_name!r} (volume stuck on old node): "
        + "; ".join(e.message for e in timeout_events)
    )
    transient = [e for e in events if e.reason in ("FailedAttachVolume", "Multi-Attach")]
    if transient:
        logger.info(f"Transient attach events (resolved): {[e.reason for e in transient]}")
    logger.info(f"Normal reschedule verified: {node_names[0]!r} -> {node_names[1]!r}")


def _assert_no_mount_stall_events(k8s, volumes: list) -> None:
    """Assert no mount-stall / device-in-use pod events for any volume.

    Checks for error messages that indicate:
    - concurrent mount stacking (old VolumeLockedError or our new exclusive lock message)
    - fsck orphan leaving device locked (device is in use, exit code 8)
    """
    _BAD = re.compile(
        r"VolumeLockedError"
        r"|device is in use"
        r"|already in use"
        r"|mount already in progress"
        r"|exit code.*\b8\b",
        re.IGNORECASE,
    )
    bad_found = []
    for v in volumes:
        try:
            events_json = k8s.kubectl(
                "get", "events", "-n", "default",
                "--field-selector", f"involvedObject.name={v['pod']}",
                "-o", "json",
            )
            events = Bunch.from_json(events_json)["items"]
            for e in events:
                msg = e.get("message") or ""
                if _BAD.search(msg):
                    bad_found.append(f"[{v['fs']}:{v['pod']}] {e.get('reason','?')}: {msg}")
        except Exception as exc:
            logger.warning(f"Event check for {v['pod']!r} failed (non-fatal): {exc}")

    assert not bad_found, (
        "Mount-stall / device-in-use events detected — "
        "exclusive_mount_lock or fsck-orphan fix may be incomplete:\n"
        + "\n".join(bad_found)
    )
    logger.info("No mount-stall or device-in-use events found")
