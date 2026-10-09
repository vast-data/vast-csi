"""NFS PVC mount churn — pressure CSI controller and node for leak hunting."""
from __future__ import annotations

import random

import pytest
from easypy.random import random_nice_name
from easypy.timing import Timer, timing
from easypy.units import HOUR, MINUTE

from e2e.logging import visible
from e2e.test_suites.common import parallel
from lib.builders.storage import PVCBuilder, StorageClassBuilder
from lib.builders.workloads import PodBuilder
from lib.constants import BUSYBOX_IMAGE, MGMT_SECRET, RESOURCE_LIVE_REPORT_EVERY, VIPPOOL_NAME


POOL_SIZE = 20
DURATION = 3 * HOUR
WORKERS = 8
PVC_SIZE = "1Gi"
BIND_TIMEOUT = 3 * MINUTE
DELETE_TIMEOUT = 3 * MINUTE
MOUNT_TIMEOUT = 5 * MINUTE
LOG_EVERY = 5 * MINUTE


def _make_pvc(name: str, storage_class: str) -> PVCBuilder:
    return PVCBuilder.new(
        name=name,
        access_modes=["ReadWriteMany"],
        storage_class_name=storage_class,
        storage=PVC_SIZE,
    )


def _pod_name(pvc_name: str) -> str:
    return pvc_name.replace("load-", "mount-", 1)


def _make_pod(pvc_name: str) -> PodBuilder:
    volume_name = "data"
    return (
        PodBuilder.new(
            name=_pod_name(pvc_name),
            container_name="writer",
            image=BUSYBOX_IMAGE,
            command=["sh", "-c", "touch /shared/ready; sleep 86400"],
        )
        .with_volume(
            volume_name,
            "/shared",
            {
                "name": volume_name,
                "persistentVolumeClaim": {"claimName": pvc_name},
            },
        )
    )


def _create_and_mount(k8s, name: str, storage_class: str) -> str:
    k8s.pvcs.create(_make_pvc(name, storage_class))
    k8s.pvcs.wait(
        timeout=BIND_TIMEOUT,
        name=name,
        error_msg=f"PVC {name!r} did not bind under load",
    )
    pod_name = _pod_name(name)
    k8s.pods.create(_make_pod(name))
    k8s.pods.wait(
        timeout=MOUNT_TIMEOUT,
        name=pod_name,
        error_msg=f"Pod {pod_name!r} did not mount PVC {name!r}",
    )
    return name


def _unmount_and_delete(k8s, name: str) -> str:
    pod_name = _pod_name(name)
    k8s.pods.delete(name=pod_name)
    k8s.pods.wait(
        timeout=DELETE_TIMEOUT,
        name=pod_name,
        condition="Deleted",
        error_msg=f"Pod {pod_name!r} did not disappear under load",
    )
    k8s.pvcs.delete(name=name)
    k8s.pvcs.wait(
        timeout=DELETE_TIMEOUT,
        name=name,
        condition="Deleted",
        error_msg=f"PVC {name!r} did not disappear under load",
    )
    return name


@pytest.mark.e2e
@pytest.mark.nfs
def test_nfs_pvc_create_delete_load(k8s, resource_sampler, pytestconfig):
    """Churn NFSv4 PVC mounts for at least 3 hours against the installed driver."""
    show = lambda msg: visible(msg, pytestconfig)
    resource_sampler.start_live_reporting(
        RESOURCE_LIVE_REPORT_EVERY,
        line_writer=show,
    )
    run_id = random_nice_name()
    storage_class = f"load-nfs4-{run_id}"
    k8s.storageclasses.create(
        StorageClassBuilder.new(
            name=storage_class,
            vip_pool_name=VIPPOOL_NAME,
        )
        .with_mount_options("vers=4.1")
        .with_secret(MGMT_SECRET)
    )

    live: list[str] = []
    created = deleted = mounted = unmounted = rounds = 0

    show(
        f"PVC load start: pool={POOL_SIZE} duration>={DURATION} "
        f"workers={WORKERS} sc={storage_class!r} run={run_id}"
    )

    sampler = resource_sampler
    with timing() as pool_timer:
        initial = [f"load-{run_id}-{i}" for i in range(POOL_SIZE)]
        parallel(
            lambda name: _create_and_mount(k8s, name, storage_class),
            initial,
            max_workers=WORKERS,
            sampler=sampler,
        )
        live.extend(initial)
        created += len(initial)
        mounted += len(initial)
    show(
        f"Pool ready: {len(live)} NFSv4 PVCs mounted in "
        f"{float(pool_timer.duration):.1f}s"
    )

    seq = POOL_SIZE
    report_timer = Timer(expiration=LOG_EVERY)
    with timing(Timer(expiration=DURATION)) as load_timer:
        while not load_timer.expired:
            sampler.raise_if_limits_exceeded()
            victim_count = random.randint(1, max(1, POOL_SIZE // 2))
            victims = random.sample(live, k=min(victim_count, len(live)))
            for name in victims:
                live.remove(name)

            replacements = [
                f"load-{run_id}-{seq + j}" for j in range(len(victims))
            ]
            seq += len(victims)

            parallel(
                lambda name: _unmount_and_delete(k8s, name),
                victims,
                max_workers=WORKERS,
                sampler=sampler,
            )
            deleted += len(victims)
            unmounted += len(victims)

            parallel(
                lambda name: _create_and_mount(k8s, name, storage_class),
                replacements,
                max_workers=WORKERS,
                sampler=sampler,
            )
            live.extend(replacements)
            created += len(replacements)
            mounted += len(replacements)

            rounds += 1
            if report_timer.expired or load_timer.expired:
                show(
                    f"round {rounds}: live={len(live)} created={created} "
                    f"deleted={deleted} mounted={mounted} unmounted={unmounted} "
                    f"elapsed={float(load_timer.elapsed):.0f}s "
                    f"remaining={float(load_timer.remain):.0f}s"
                )
                report_timer.reset()

    assert len(live) == POOL_SIZE, f"pool drifted: {len(live)} != {POOL_SIZE}"
    show(
        f"PVC load done: rounds={rounds} created={created} deleted={deleted} "
        f"mounted={mounted} unmounted={unmounted} "
        f"elapsed={float(load_timer.duration):.1f}s"
    )
