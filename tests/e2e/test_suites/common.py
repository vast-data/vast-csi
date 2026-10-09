"""Shared helpers for CSI test suites (block, nfs, cosi)."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pytest
from easypy.bunch import Bunch
from easypy.timing import Timer, wait
from easypy.units import MINUTE
from plumbum.commands.processes import ProcessExecutionError

from lib.builders.storage import PVCBuilder
from lib.builders.workloads import PodBuilder
from lib.constants import BUSYBOX_IMAGE, CSI_NAMESPACE
from e2e.logging import logger

WRITE_COMMAND = ["sh", "-c", "while true; do date -Iseconds >> /shared/$HOSTNAME; sleep 1; done"]
CONCURRENT_VOLUME_COUNT = 3
POD_MOUNT_PATH = "/shared"


def skip_unless_selinux_mount(k8s, *, what: str) -> None:
    """ROX needs OpenShift SELinuxMount + Pod seLinuxChangePolicy=MountOption."""
    if k8s.selinux_mount:
        return
    pytest.skip(
        f"{what} needs OpenShift FeatureGate SELinuxMount "
        "(off on CRC; RWO tests do not need it)."
    )


def writer_has_data(k8s, pod_name: str, filename: str | None = None) -> bool:
    """True when the writer has a non-empty file. A missing file is False, not an error.

    ``kubectl exec ... test -s`` exits 1 when the file is absent; plumbum raises.
    easypy ``wait()`` only retries ``PredicateNotSatisfied``, so that would abort
    the wait on the first poll after the container becomes Ready.
    """
    path = f"{POD_MOUNT_PATH}/{filename or pod_name}"
    try:
        out = k8s.pods.exec(pod_name, f"sh -c 'test -s {path} && echo ok || true'")
    except ProcessExecutionError:
        return False
    return (out or "").strip() == "ok"


def parse_iso_date(text: str) -> datetime:
    return datetime.fromisoformat(text.strip())


def files_in_pod(k8s, pod_name: str, path: str = POD_MOUNT_PATH) -> set[str]:
    return set(k8s.pods.ls(pod_name, path))


def read_in_pod(k8s, pod_name: str, path: str) -> str:
    return k8s.pods.read(pod_name, path)


def make_filesystem_pvc(
    name: str,
    storage_class: str,
    storage: str = "2Gi",
    access_modes: list[str] | None = None,
) -> PVCBuilder:
    return (
        PVCBuilder.new(
            name=name,
            access_modes=access_modes or ["ReadWriteOnce"],
            storage_class_name=storage_class,
            storage=storage,
        )
        .with_volume_mode("Filesystem")
    )


def flush_writer_data(k8s, pod_name: str, filename: str | None = None) -> None:
    """Flush the writer's file to disk before snapshotting it.

    Deliberately not busybox ``sync``, which takes no arguments and flushes
    every filesystem on the node — one wedged volume elsewhere would block it
    forever. ``fsync`` touches only this pod's volume.
    """
    path = f"{POD_MOUNT_PATH}/{filename or pod_name}"
    k8s.pods.exec(pod_name, f"fsync {path}")


def make_writer_pod(
    pod_name: str,
    pvc_name: str,
    *,
    mount_path: str = "/shared",
    volume_name: str = "data",
    command: list[str] | None = None,
    image: str = BUSYBOX_IMAGE,
    node_name: str | None = None,
    read_only: bool = False,
) -> PodBuilder:
    builder = (
        PodBuilder.new(name=pod_name, container_name="writer",
                       image=image, command=command or WRITE_COMMAND)
        .with_volume(
            volume_name, mount_path,
            {"name": volume_name, "persistentVolumeClaim": {"claimName": pvc_name}},
            read_only=read_only,
        )
    )
    if node_name:
        builder = builder.with_spec(nodeSelector={"kubernetes.io/hostname": node_name})
    return builder


def wait_pods_healthy(
    k8s,
    pod_names: list[str],
    node_name: str,
    *,
    context: str = "soak",
) -> None:
    """Fail if any writer left Running; include last logs for diagnosis."""
    failures = []
    for pod_name in pod_names:
        pod = k8s.pods.get(name=pod_name)
        phase = getattr(getattr(pod, "status", None), "phase", "Unknown")
        if phase != "Running":
            try:
                logs = k8s.kubectl(
                    "logs", pod_name, "-n", CSI_NAMESPACE, "--tail=20"
                )
            except Exception:
                logs = "<unavailable>"
            failures.append(
                f"{pod_name!r} phase={phase!r} on {node_name!r}\n{logs}"
            )
    if failures:
        raise RuntimeError(f"IO failure during {context}:\n" + "\n".join(failures))


def parallel(fn, items, max_workers=10, sampler=None):
    """Run fn(item) for each item in a thread pool; re-raise the first exception.

    Given a sampler, every item rechecks the CSI hard limits before it starts,
    so a breach aborts the queued work instead of driving load for the rest of
    the wave.
    """
    if not items:
        return

    def guarded(item):
        if sampler is not None:
            sampler.raise_if_limits_exceeded()
        return fn(item)

    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        futures = [pool.submit(guarded, item) for item in items]
        for future in as_completed(futures):
            future.result()


def soak(seconds: float, resource_sampler) -> None:
    """Sleep while polling CSI resource hard limits so a leak fails the test promptly."""
    timer = Timer(expiration=seconds)
    while not timer.expired:
        resource_sampler.raise_if_limits_exceeded()
        time.sleep(min(1.0, float(timer.remain)))


def wait_volumes_detached(
    k8s, pvc_names: list[str], source_node: str, timeout: int = 15 * MINUTE
):
    """Wait until ALL VolumeAttachments for the given PVCs are gone from source_node."""
    pv_names = [k8s.pvcs.get(name=pvc).spec.volumeName for pvc in pvc_names]
    logger.info(f"Waiting for {len(pv_names)} PV(s) to fully detach from {source_node!r}")

    def _all_detached():
        items = Bunch.from_json(k8s.kubectl("get", "volumeattachments", "-o", "json"))["items"]
        attached_pvs = {
            a.spec.source.persistentVolumeName
            for a in items
            if a.spec.nodeName == source_node
        }
        still_present = [pv for pv in pv_names if pv in attached_pvs]
        if still_present:
            logger.info(f"Still attached to {source_node!r}: {still_present}")
            return False
        return True

    wait(timeout, _all_detached,
         message=f"VolumeAttachment(s) still present on {source_node!r}: {pv_names}")
    logger.info(f"All {len(pv_names)} PV(s) fully detached from {source_node!r}")


def _first_pod(k8s, *, name: str | None = None, labels: dict | None = None, namespace: str = CSI_NAMESPACE):
    if bool(name) == bool(labels):
        raise ValueError("provide exactly one of name or labels")
    pods = k8s.pods.get(name=name, namespace=namespace, labels=labels)
    if not pods:
        target = f"name={name!r}" if name else f"labels={labels!r}"
        raise AssertionError(f"No pods matching {target} in namespace {namespace!r}")
    if getattr(pods, "metadata", None) is not None:
        return pods
    return pods[0]


def container_env(
    k8s,
    *,
    container: str,
    name: str | None = None,
    labels: dict | None = None,
    namespace: str = CSI_NAMESPACE,
) -> dict[str, str | None]:
    """Literal env values for a container. Entries from valueFrom have no ``value``."""
    pod = _first_pod(k8s, name=name, labels=labels, namespace=namespace)
    match = next(
        (item for item in pod.spec.containers if item.name == container),
        None,
    )
    assert match is not None, (
        f"Container {container!r} not found on pod {pod.metadata.name} "
        f"(have {[c.name for c in pod.spec.containers]})"
    )
    return {item.name: item.get("value") for item in match.get("env", [])}


def pod_logs(
    k8s,
    *,
    name: str | None = None,
    labels: dict | None = None,
    namespace: str = CSI_NAMESPACE,
    container: str | None = None,
    since: str | None = None,
) -> str:
    pod = _first_pod(k8s, name=name, labels=labels, namespace=namespace)
    args = ["logs", pod.metadata.name, "-n", namespace]
    if container:
        args.extend(["-c", container])
    if since:
        args.append(f"--since={since}")
    return k8s.kubectl(*args)


def assert_text_in_logs(
    k8s,
    text: str,
    *,
    name: str | None = None,
    labels: dict | None = None,
    namespace: str = CSI_NAMESPACE,
    container: str | None = None,
    since: str | None = None,
) -> str:
    """Fail unless *text* appears in the selected pod/container logs."""
    logs = pod_logs(
        k8s,
        name=name,
        labels=labels,
        namespace=namespace,
        container=container,
        since=since,
    )
    assert text in logs, (
        f"{text!r} not found in logs of "
        f"{name or labels} namespace={namespace!r} container={container!r}:\n"
        f"{logs[-4000:]}"
    )
    return logs
