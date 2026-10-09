"""Wave-based block provisioning, IO, and cross-node rescheduling stress test."""
from __future__ import annotations

import random

import pytest
from easypy.random import random_nice_name
from easypy.timing import timing
from easypy.units import MINUTE

from e2e.logging import logger
from e2e.test_suites.common import make_writer_pod, parallel, soak, wait_pods_healthy
from lib.builders.storage import PVCBuilder
from lib.constants import block_storage_class

_VOLUME_SIZE = "150Gi"
_FS_TYPES = ("ext4", "ext3", "xfs")
_WRITE_COMMAND = [
    "sh",
    "-c",
    "while true; do "
    "dd if=/dev/zero of=/data/stress bs=4M count=256 "
    "conv=notrunc oflag=dsync 2>&1 || exit 1; "
    "done",
]


@pytest.mark.e2e
@pytest.mark.block
@pytest.mark.stress
def test_block_wave_stress(k8s, resource_sampler, pytestconfig):
    """Provision, format, write, and reschedule block PVCs in repeated waves."""
    nodes = k8s.nodes.names()
    if len(nodes) < 2:
        pytest.skip(f"Block reschedule stress requires at least two nodes; found {nodes}")

    waves = pytestconfig.getoption("--stress-waves")
    pvcs_per_wave = pytestconfig.getoption("--block-stress-pvcs")
    io_soak = pytestconfig.getoption("--stress-io-soak")

    sampler = resource_sampler
    sampler.start_live_reporting(interval_sec=20)
    summaries = []
    for wave in range(1, waves + 1):
        suffix = random_nice_name(max_length=16)
        fs_type = random.choice(_FS_TYPES)
        pvc_names = [
            f"stress-blk-{wave}-{index}-{suffix}"
            for index in range(pvcs_per_wave)
        ]
        pod_a_names = [
            f"stress-blk-a-{wave}-{i}-{suffix}" for i in range(pvcs_per_wave)
        ]
        pod_b_names = [
            f"stress-blk-b-{wave}-{i}-{suffix}" for i in range(pvcs_per_wave)
        ]
        node_a, node_b = (
            (nodes[0], nodes[1]) if wave % 2 else (nodes[1], nodes[0])
        )
        logger.notice(
            f"Block stress wave {wave}/{waves}: {pvcs_per_wave} PVCs, "
            f"fs={fs_type}, {node_a!r} -> {node_b!r}"
        )

        with timing() as bind_timer:
            for pvc_name in pvc_names:
                k8s.pvcs.create(
                    PVCBuilder.new(
                        name=pvc_name,
                        access_modes=["ReadWriteOnce"],
                        storage_class_name=block_storage_class(fs_type=fs_type),
                        storage=_VOLUME_SIZE,
                    )
                )
            parallel(
                lambda name: k8s.pvcs.wait(
                    timeout=5 * MINUTE,
                    name=name,
                    error_msg=f"Block PVC {name!r} did not bind",
                ),
                pvc_names,
                sampler=sampler,
            )
        sampler.raise_if_limits_exceeded()

        with timing() as mount_timer:
            for pvc_name, pod_name in zip(pvc_names, pod_a_names):
                k8s.pods.create(
                    make_writer_pod(
                        pod_name,
                        pvc_name,
                        mount_path="/data",
                        volume_name="block-volume",
                        command=_WRITE_COMMAND,
                        node_name=node_a,
                    )
                )
            parallel(
                lambda name: k8s.pods.wait(
                    timeout=5 * MINUTE,
                    name=name,
                    error_msg=f"Block writer {name!r} did not start",
                ),
                pod_a_names,
                sampler=sampler,
            )
        soak(io_soak, sampler)
        wait_pods_healthy(k8s, pod_a_names, node_a, context="block stress")

        parallel(
            lambda name: k8s.pods.delete(name=name, wait=False),
            pod_a_names,
            sampler=sampler,
        )
        with timing() as reschedule_timer:
            for pvc_name, pod_name in zip(pvc_names, pod_b_names):
                k8s.pods.create(
                    make_writer_pod(
                        pod_name,
                        pvc_name,
                        mount_path="/data",
                        volume_name="block-volume",
                        command=_WRITE_COMMAND,
                        node_name=node_b,
                    )
                )
            parallel(
                lambda name: k8s.pods.wait(
                    timeout=5 * MINUTE,
                    name=name,
                    error_msg=f"Block writer {name!r} did not reschedule",
                ),
                pod_b_names,
                sampler=sampler,
            )
        soak(io_soak, sampler)
        wait_pods_healthy(k8s, pod_b_names, node_b, context="block stress")

        with timing() as delete_timer:
            parallel(
                lambda name: k8s.pods.delete(name=name),
                pod_b_names,
                sampler=sampler,
            )
            parallel(
                lambda name: k8s.pvcs.delete(name=name),
                pvc_names,
                sampler=sampler,
            )
        sampler.raise_if_limits_exceeded()

        summaries.append(
            (
                wave,
                fs_type,
                float(bind_timer.duration),
                float(mount_timer.duration),
                float(reschedule_timer.duration),
                float(delete_timer.duration),
            )
        )
        logger.notice(
            f"Block wave {wave}: fs={fs_type} "
            f"bind={float(bind_timer.duration):.1f}s "
            f"mount={float(mount_timer.duration):.1f}s "
            f"reschedule={float(reschedule_timer.duration):.1f}s "
            f"delete={float(delete_timer.duration):.1f}s"
        )

    logger.notice(
        "Block stress summary:\n"
        + "\n".join(
            f"wave={wave} fs={fs_type} bind={bind:.1f}s mount={mount:.1f}s "
            f"reschedule={reschedule:.1f}s delete={delete:.1f}s"
            for wave, fs_type, bind, mount, reschedule, delete in summaries
        )
    )
