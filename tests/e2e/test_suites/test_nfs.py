"""NFS / vastcsi chart test bodies."""
from datetime import datetime

import pytest
from easypy.collections import grouped
from easypy.random import random_nice_name
from easypy.timing import wait
from easypy.units import MINUTE, GiB
from plumbum import FG

from lib.builders.storage import PVCBuilder, VolumeSnapshotBuilder
from lib.builders.workloads import DeploymentBuilder, PodBuilder, StatefulSetBuilder
from lib.constants import BUSYBOX_IMAGE, CSI_QUOTA_PREFIX, MGMT_SECRET, NFS_MOUNT_OPTIONS, ROOT_EXPORT, SNAPSHOT_CLASS, VIEW_POLICY_NAME, VIPPOOL_NAME, nfs_storage_class
from e2e.logging import logger
from e2e.test_suites.common import (
    files_in_pod,
    parse_iso_date,
    read_in_pod,
)


def csi_quota_for_pvc(system, pvc_claim):
    """Return the VAST quota for a bound PVC, or None if not found."""
    pvc_name = pvc_claim.metadata.name
    vol_name = getattr(pvc_claim.spec, "volumeName", None) or ""
    by_pvc = system.quotas.single(
        lambda q: q.name.startswith(CSI_QUOTA_PREFIX) and pvc_name in q.name
    )
    if by_pvc:
        return by_pvc
    if vol_name:
        return system.quotas.single(
            lambda q: q.name.startswith(CSI_QUOTA_PREFIX) and vol_name in q.name
        )
    return None


# ---------------------------------------------------------------------------
# Test bodies
# ---------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_basic_apps_and_pvcs(system, k8s):
    replicas_rwo = 1
    replicas_rwx = 3
    labels = dict(run=random_nice_name())
    storage_class_name = nfs_storage_class()

    pvc_rwo = PVCBuilder.new(access_modes=['ReadWriteOnce'], storage_class_name=storage_class_name, storage='1Gi')
    pvc_rwx = PVCBuilder.new(access_modes=['ReadWriteMany'], storage_class_name=storage_class_name, storage='2Gi')
    k8s.pvcs.create(pvc_rwo)
    k8s.pvcs.create(pvc_rwx)
    pvcs = [pvc_rwo, pvc_rwx]

    deployment_replicas = [replicas_rwo, replicas_rwx]
    k8s.deployments.create(DeploymentBuilder.new(pvc=pvc_rwo.name, replicas=replicas_rwo, extra_labels=labels))
    k8s.deployments.create(DeploymentBuilder.new(pvc=pvc_rwx.name, replicas=replicas_rwx, extra_labels=labels))
    extra_sc = nfs_storage_class(1)
    pvc_extra = PVCBuilder.new(access_modes=['ReadWriteOnce'], storage_class_name=extra_sc, storage='1Gi')
    k8s.pvcs.create(pvc_extra)
    pvcs.append(pvc_extra)
    k8s.deployments.create(DeploymentBuilder.new(pvc=pvc_extra.name, replicas=replicas_rwo, extra_labels=labels))
    deployment_replicas.append(replicas_rwo)
    try:
        expected_apps = sum(deployment_replicas)
        apps = k8s.pods.wait(
            timeout=MINUTE * 5, labels=labels, error_msg=f"not all pods out of {expected_apps} are running.",
        )
        assert expected_apps == len(apps)
    except Exception:
        for pod in k8s.pods.get(labels=labels):
            pod_name = pod.metadata.name
            logger.info(f"--- {pod_name} ---")
            k8s.pods.describe(name=pod_name)
        raise
    finally:
        k8s.kubectl["get", "-o", "wide", "pods,pvc,events"] & FG
    claims = k8s.pvcs.get(name=[p.name for p in pvcs])
    apps_by_pvc = grouped(
        apps,
        lambda app: app.spec.volumes[0].persistentVolumeClaim.claimName,
        lambda app: app.metadata.name,
    )
    logger.info("checking volume contents via pods")
    for claim in claims:
        logger.info(f"Checking {claim.spec.volumeName}")
        app_names = set(apps_by_pvc[claim.metadata.name])
        sample_pod = next(iter(app_names))
        found = files_in_pod(k8s, sample_pod)
        missing = app_names - found
        assert not missing, (
            f"Missing app files in volume {claim.spec.volumeName}: {missing} (found {found})"
        )
        logger.info(f"  - Found {len(found)} app files - all good!")

    pvc = claims[0]
    first_quota = wait(
        MINUTE,
        lambda: csi_quota_for_pvc(system, pvc),
        message=f"no CSI quota for {pvc.metadata.name!r} (volume {pvc.spec.volumeName!r})",
    )
    logger.info(f"Checking volume expansion via {pvc.metadata.name} ({first_quota.hard_limit=})")

    assert first_quota.name.startswith('csi:')
    assert first_quota.hard_limit < 2 * GiB
    pvc.spec.resources.requests.storage = '5Gi'
    k8s.pvcs.apply([pvc])

    wait(
        MINUTE,
        lambda: (q := csi_quota_for_pvc(system, pvc)) is not None and q.hard_limit >= 5 * GiB,
        message=f"{first_quota} hasn't been expanded",
    )
    first_quota = csi_quota_for_pvc(system, pvc)
    logger.info(f"Quota expanded: {first_quota.hard_limit}")

    extra_pvc = claims[-1]
    last_quota = csi_quota_for_pvc(system, extra_pvc)
    assert last_quota is not None, f"no CSI quota for {extra_pvc.metadata.name!r}"
    assert last_quota.name.startswith('csi:2:')

    views = system.views
    assert any(first_quota.path == v.path for v in views)
    assert any(last_quota.path == v.path for v in views)


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_ephemeral_volumes(system, k8s):
    suffix = random_nice_name(max_length=24)
    pod_name = f"ev-pod-{suffix}"
    volume = {
        "name": "my-eph-vol",
        "csi": {
            "driver": "csi.vastdata.com",
            "nodePublishSecretRef": {"name": MGMT_SECRET},
            "volumeAttributes": {
                "size": "1G",
                "root_export": ROOT_EXPORT,
                "vip_pool_name": VIPPOOL_NAME,
                "view_policy": VIEW_POLICY_NAME,
                "mount_options": ",".join(NFS_MOUNT_OPTIONS),
            },
        },
    }
    k8s.pods.create(
        PodBuilder.new(name=pod_name, container_name="my-frontend",
                       image=BUSYBOX_IMAGE)
        .with_volume("my-eph-vol", "/shared", volume)
    )
    k8s.pods.wait(
        timeout=MINUTE,
        name=pod_name,
        error_msg=f"the pod {pod_name!r} was not moved to the running state within the allotted period",
    )
    quota = wait(MINUTE, lambda: system.quotas.single(lambda q: pod_name in q.name), message=f"no quota for {pod_name}")
    wait(90, lambda: quota.used_capacity > 0, message=f"{quota} is still empty")
    k8s.pods.delete(name=pod_name)
    wait(MINUTE, lambda: quota.was_removed, message=f"{quota} is still there")


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_snapshot_restore(system, k8s):
    suffix = random_nice_name(max_length=24)
    snap_name = f"snap-restore-{suffix}"
    vol_name = f"vol-restore-{suffix}"
    restore_pvc_name = f"pvc-restore-{suffix}"
    storage_class_name = nfs_storage_class()
    snap_class = SNAPSHOT_CLASS

    k8s.pvcs.create(PVCBuilder.new(name=vol_name, access_modes=["ReadWriteOnce"],
                                   storage_class_name=storage_class_name, storage="1Gi"))
    sts_name = f"test-app-{suffix}"
    k8s.sts.create(StatefulSetBuilder.new(name=sts_name, pvc=vol_name, replicas=1))

    expected_pod_name = f"{sts_name}-0"
    k8s.pods.wait(
        timeout=90,
        name=expected_pod_name,
        error_msg=f"the pod {expected_pod_name!r} was not moved to the running state within the allotted period",
    )
    logger.info("Apps deployed")

    k8s.volumesnapshots.create(VolumeSnapshotBuilder.new(
        name=snap_name, pvc_name=vol_name, snapshot_class_name=snap_class,
    ))
    with logger.indented("waiting for snapshot"):
        uid = k8s.volumesnapshots.wait(
            timeout=5 * MINUTE, name=snap_name, error_msg=f"no '{snap_name}'",
        )['metadata']['uid']
        wait(5 * MINUTE, lambda: system.snapshots.single(lambda s: uid in s.name),
             message=f"no snapshot for {uid}")

    snap_source = {"name": snap_name, "kind": "VolumeSnapshot", "apiGroup": "snapshot.storage.k8s.io"}
    k8s.pvcs.create(
        PVCBuilder.new(name=restore_pvc_name, access_modes=['ReadWriteOnce'],
                       storage_class_name=storage_class_name, storage='1Gi')
        .with_data_source(**snap_source)
    )
    restore_sts_name = f"restore-{suffix}"
    k8s.sts.create(StatefulSetBuilder.new(name=restore_sts_name, pvc=restore_pvc_name,
                                          replicas=1, command=["sleep", "600"]))
    expected_pods = [f"{restore_sts_name}-0"]

    restore_pvc2_name = f"restore-pvc2-{suffix}"
    k8s.pvcs.create(
        PVCBuilder.new(name=restore_pvc2_name, access_modes=['ReadOnlyMany'],
                       storage_class_name=storage_class_name, storage='1Gi')
        .with_data_source(**snap_source)
    )
    restore_sts2_name = f"restore2-{suffix}"
    k8s.sts.create(StatefulSetBuilder.new(name=restore_sts2_name, pvc=restore_pvc2_name,
                                          replicas=1, command=["sleep", "600"]))
    expected_pods.append(f"{restore_sts2_name}-0")

    k8s.pods.wait(
        timeout=90,
        name=tuple(expected_pods),
        error_msg=f"the pod(s) {expected_pods!r} was not moved to the running state within the allotted period",
    )

    snap_content_data = k8s.volumesnapshotcontents.get()[0]
    assert snap_content_data.status.readyToUse is True
    assert snap_content_data.spec.driver == 'csi.vastdata.com'

    for pod in expected_pods:
        date = read_in_pod(k8s, pod, f"/shared/{expected_pod_name}")
        dt = parse_iso_date(date)
        assert isinstance(dt, datetime)


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_retain_policy(k8s):
    storage_class_name = nfs_storage_class(1)

    suffix = random_nice_name(max_length=24)
    pvc1_name = f"vast-pvc-{suffix}-1"
    pvc2_name = f"vast-pvc-{suffix}-2"

    k8s.pvcs.create(PVCBuilder.new(name=pvc1_name, access_modes=['ReadWriteOnce'],
                                   storage_class_name=storage_class_name, storage='1Gi'))
    pvc = k8s.pvcs.wait(name=pvc1_name, error_msg="The Bound status was not attained by the PVC.")
    k8s.pvcs.delete(name=pvc1_name)
    k8s.pvcs.wait(name=pvc1_name, condition="Deleted")
    pv = k8s.pvs.get(name=pvc.spec.volumeName)
    assert pv.status.phase == "Released"

    k8s.kubectl["patch", "pv", pv.metadata.name, "-p", '{"spec":{"claimRef": null}}'] & FG
    assert k8s.pvs.get(name=pvc.spec.volumeName).status.phase == "Available"

    k8s.pvcs.create(
        PVCBuilder.new(name=pvc2_name, access_modes=['ReadWriteOnce'],
                       storage_class_name=storage_class_name, storage='1Gi')
        .with_volume_name(pv.metadata.name)
    )
    k8s.pvcs.wait(name=pvc2_name, error_msg="The Bound status was not attained by the PVC.")
    assert k8s.pvs.get(name=pv.metadata.name).status.phase == "Bound"

    sts_name = f"retain-app-{suffix}"
    k8s.sts.create(StatefulSetBuilder.new(name=sts_name, pvc=pvc2_name, replicas=1))
    expected_pod_name = f"{sts_name}-0"
    k8s.pods.wait(
        timeout=90,
        name=expected_pod_name,
        error_msg=f"the pod {expected_pod_name!r} was not moved to the running state within the allotted period",
    )

    date = read_in_pod(k8s, expected_pod_name, f"/shared/{expected_pod_name}")
    dt = parse_iso_date(date)
    assert isinstance(dt, datetime)


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_clone_volume(k8s):
    storage_class_name = nfs_storage_class(1)

    suffix = random_nice_name(max_length=24)
    pvc_name = f"pvc-clone-{suffix}"
    sts_name = f"sts-clone-{suffix}"

    k8s.pvcs.create(PVCBuilder.new(name=pvc_name, access_modes=["ReadWriteOnce"],
                                   storage_class_name=storage_class_name, storage="1Gi"))
    k8s.sts.create(StatefulSetBuilder.new(name=sts_name, pvc=pvc_name, replicas=1))
    source_pod_name = f"{sts_name}-0"
    k8s.pods.wait(
        timeout=90,
        name=source_pod_name,
        error_msg=f"the pod {source_pod_name!r} was not moved to the running state within the allotted period",
    )
    logger.info("Apps deployed")

    k8s.sts.delete(name=sts_name)
    k8s.pods.wait(
        name=source_pod_name,
        error_msg=f"the pod {source_pod_name!r} was not deleted within the allotted period",
        condition="Deleted",
    )

    clone_pvc_name = f"pvc-clone-{suffix}-copy"
    k8s.pvcs.create(
        PVCBuilder.new(name=clone_pvc_name, access_modes=["ReadWriteOnce"],
                       storage_class_name=storage_class_name, storage="1Gi")
        .with_data_source(name=pvc_name, kind="PersistentVolumeClaim")
    )
    k8s.pvcs.wait(name=clone_pvc_name, error_msg="The Bound status was not attained by the PVC.")

    clone_sts_name = f"sts-clone-{suffix}-copy"
    k8s.sts.create(StatefulSetBuilder.new(name=clone_sts_name, pvc=clone_pvc_name,
                                          replicas=1, command=["sleep", "600"]))
    clone_pod_name = f"{clone_sts_name}-0"
    k8s.pods.wait(
        timeout=90,
        name=clone_pod_name,
        error_msg=f"the pod {clone_pod_name!r} was not moved to the running state within the allotted period",
    )

    date = read_in_pod(k8s, clone_pod_name, f"/shared/{source_pod_name}")
    dt = parse_iso_date(date)
    assert isinstance(dt, datetime)


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_reschedule_normal(k8s):
    """Reschedule an NFS RWO volume node A → node B under continuous IO (VCSI-591).

    Writer keeps the mount busy so NodeUnpublishVolume may briefly hit umount
    EBUSY (exit 16).  Kubelet must retry until the volume detaches and the pod
    reaches Running on the target node within 3 minutes.  Final outcome must be
    success — transient EBUSY alone is not a failure.
    """
    storage_class = nfs_storage_class()
    suffix = random_nice_name(max_length=24)
    pvc_name = f"nfs-pvc-{suffix}"
    pod_name = f"nfs-pod-{suffix}"

    node_names = k8s.nodes.names()
    if len(node_names) < 2:
        pytest.skip(f"Expected 2+ nodes for reschedule test, found: {node_names}")

    k8s.pvcs.create(PVCBuilder.new(
        name=pvc_name,
        access_modes=["ReadWriteOnce"],
        storage_class_name=storage_class,
        storage="2Gi",
    ))
    k8s.pvcs.wait(timeout=3 * MINUTE, name=pvc_name, error_msg=f"PVC {pvc_name!r} did not bind")

    write_cmd = [
        "sh", "-c",
        "while true; do "
        "dd if=/dev/zero of=/shared/stress bs=1M count=32 conv=notrunc oflag=dsync 2>&1 || exit 1; "
        "done",
    ]
    pod_builder = (
        PodBuilder.new(
            name=pod_name,
            container_name="writer",
            image=BUSYBOX_IMAGE,
            command=write_cmd,
        )
        .with_volume(
            "nfs-data", "/shared",
            {"name": "nfs-data", "persistentVolumeClaim": {"claimName": pvc_name}},
        )
        .with_spec(nodeSelector={"kubernetes.io/hostname": node_names[0]})
    )
    k8s.pods.create(pod_builder)
    k8s.pods.wait(timeout=5 * MINUTE, name=pod_name, error_msg=f"Pod {pod_name!r} did not start")
    logger.info(f"Pod running on {node_names[0]!r}, rescheduling to {node_names[1]!r}")

    # Delete without waiting; immediately recreate on target (EBUSY overlap path).
    k8s.pods.delete(name=pod_name)
    pod_builder = pod_builder.with_spec(nodeSelector={"kubernetes.io/hostname": node_names[1]})
    k8s.pods.create(pod_builder)
    second_pod = k8s.pods.wait(
        timeout=3 * MINUTE,
        name=pod_name,
        error_msg=(
            f"Pod {pod_name!r} did not reschedule to {node_names[1]!r} within 3 min "
            f"(possible NodeUnpublishVolume / umount hang regression)"
        ),
    )
    assert second_pod.spec.nodeName == node_names[1], (
        f"Expected pod on {node_names[1]!r}, got {second_pod.spec.nodeName!r}"
    )
    logger.info(f"Normal NFS reschedule verified: {node_names[0]!r} -> {node_names[1]!r}")
