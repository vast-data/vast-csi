"""In-memory log of k8s create operations for test teardown (not persistent storage)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from e2e.logging import logger

from e2e.constants import CSI_NAMESPACE, MGMT_SECRET

K8S_CLEANUP_MAX_WORKERS = 8

if TYPE_CHECKING:
    from e2e.k8s._base import K8S, KubernetesResource

_CLUSTER_SCOPED = frozenset({"storageclass", "pv", "namespace"})


def _is_protected(entry: RecordedCreation) -> bool:
    """Never delete the shared ``default`` namespace or the VMS mgmt secret."""
    if entry.resource_type == "namespace" and entry.name in ("default", CSI_NAMESPACE):
        return True
    if entry.resource_type == "secret" and entry.name == MGMT_SECRET:
        return True
    return False


@dataclass(frozen=True)
class RecordedCreation:
    resource_type: str
    name: str
    namespace: Optional[str] = "default"

    @property
    def cluster_scoped(self) -> bool:
        return self.resource_type in _CLUSTER_SCOPED


class CreationRecorder:
    """Append-only log of resources created during a test; used to undo them on cleanup."""

    def __init__(self) -> None:
        self._entries: list[RecordedCreation] = []

    def clear(self) -> None:
        self._entries.clear()

    def record(self, resource_type: str, name: str, namespace: Optional[str] = "default") -> None:
        entry = RecordedCreation(resource_type, name, namespace)
        if _is_protected(entry):
            return
        self._entries.append(entry)

    def _manager(self, k8s: K8S, resource_type: str) -> KubernetesResource:
        table = {
            "pvc": "pvcs",
            "pv": "pvs",
            "storageclass": "storageclasses",
            "volumesnapshot": "volumesnapshots",
            "volumesnapshotcontent": "volumesnapshotcontents",
            "pod": "pods",
            "deployment": "deployments",
            "statefulset": "sts",
            "namespace": "namespaces",
            "secret": "secrets",
            "bucketclaim": "bucketclaims",
            "bucketaccessclass": "bucketaccessclasses",
            "bucketaccess": "bucketaccesses",
            "vastcsidrivers": "vastcsidrivers",
            "vastclusters": "vastclusters",
            "vaststorages": "vaststorages",
        }
        try:
            attr = table[resource_type]
        except KeyError as exc:
            raise KeyError(f"No k8s manager for resource type {resource_type!r}") from exc
        return getattr(k8s, attr)

    def _undo_one(self, k8s: K8S, entry: RecordedCreation) -> None:
        if _is_protected(entry):
            return
        try:
            if entry.resource_type == "secret":
                k8s.secrets.delete(entry.name, namespace=entry.namespace or "default")
                return
            manager = self._manager(k8s, entry.resource_type)
            if entry.cluster_scoped:
                manager.delete(entry.name, namespace=None)
            else:
                manager.delete(entry.name, namespace=entry.namespace or "default")
        except Exception as exc:
            logger.warning(f"cleanup {entry.resource_type}/{entry.name}: {exc}")

    def cleanup(self, k8s: K8S, *, parallel: bool = True) -> None:
        if not self._entries:
            return
        pending = list(reversed(self._entries))
        self.clear()
        logger.info(f"Undoing {len(pending)} recorded k8s creations")
        try:
            if parallel and len(pending) > 1:
                workers = min(K8S_CLEANUP_MAX_WORKERS, len(pending))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [pool.submit(self._undo_one, k8s, entry) for entry in pending]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as exc:
                            logger.warning(f"cleanup worker: {exc}")
            else:
                for entry in pending:
                    self._undo_one(k8s, entry)
        except Exception as exc:
            logger.warning(f"k8s cleanup raised: {exc}")
