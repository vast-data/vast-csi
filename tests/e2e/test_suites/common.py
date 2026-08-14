"""Shared helpers for CSI test suites (block, nfs, cosi)."""
from __future__ import annotations

from datetime import datetime

from easypy.bunch import Bunch
from easypy.timing import wait
from easypy.units import MINUTE
from plumbum.commands.processes import ProcessExecutionError

from lib.builders.storage import PVCBuilder
from lib.builders.workloads import PodBuilder
from lib.constants import BUSYBOX_IMAGE
from e2e.logging import logger

WRITE_COMMAND = ["sh", "-c", "while true; do date -Iseconds >> /shared/$HOSTNAME; sleep 1; done"]
CONCURRENT_VOLUME_COUNT = 3
POD_MOUNT_PATH = "/shared"


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


def make_writer_pod(
    pod_name: str,
    pvc_name: str,
    *,
    mount_path: str = "/shared",
    volume_name: str = "data",
    command: list[str] | None = None,
    image: str = BUSYBOX_IMAGE,
) -> PodBuilder:
    return (
        PodBuilder.new(name=pod_name, container_name="writer",
                       image=image, command=command or WRITE_COMMAND)
        .with_volume(
            volume_name, mount_path,
            {"name": volume_name, "persistentVolumeClaim": {"claimName": pvc_name}},
        )
    )


def list_node_names(k8s) -> list[str]:
    nodes_obj = Bunch.from_json(k8s.kubectl("get", "nodes", "-o", "json"))
    return [n.metadata.name for n in nodes_obj["items"]]


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
