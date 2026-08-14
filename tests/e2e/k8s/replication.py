"""K8s resource managers for VastVolumeReplication, VastStorageClassReplication,
and VastReplicationContent custom resources.
"""
from __future__ import annotations

from easypy.timing import wait
from easypy.units import MINUTE
from e2e.logging import logger

from e2e.k8s._base import KubernetesResource

# SyncStatus values (mirror vastdata.com/v1alpha1 constants)
SYNC_COMPLETED = "Completed"
SYNC_IN_PROGRESS = "InProgress"
SYNC_DELETING = "Deleting"
SYNC_ERROR = "Error"
SYNC_FAILED = "Failed"
SYNC_UNREACHABLE = "Unreachable"
SYNC_INVALID = "Invalid"


_TERMINAL_SYNC_STATUSES = {SYNC_ERROR, SYNC_FAILED, SYNC_INVALID, SYNC_UNREACHABLE}


class VastVolumeReplication(KubernetesResource):
    """Manager for VastVolumeReplication (vvr) custom resources."""

    resource_type = "vastvolumereplications"
    # VVRs are cleaned up via explicit add_cleanup(k8s.vvrs.delete, …) rather
    # than the creation recorder to keep the recorder's manager table simple.
    record_on_create = False

    def create(self, builder, record_on_create=None) -> object:
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)

    def wait_sync_status(
        self,
        name: str,
        expected: str,
        namespace: str = "default",
        timeout: int = 15 * MINUTE,
    ) -> object:
        """Block until status.syncStatus == expected or timeout.

        Returns False (triggering a retry) while the status is still transitioning.
        Raises immediately only for terminal error states so the caller gets a
        clear message without waiting out the full timeout.
        """
        logger.info(f"Waiting for VVR {name!r} to reach syncStatus={expected!r}")

        def _check():
            obj = self.get(name, namespace)
            got = (obj.get("status") or {}).get("syncStatus", "")
            if got == expected:
                return obj
            if got in _TERMINAL_SYNC_STATUSES:
                self.describe(name, namespace)
                raise Exception(f"VVR {name!r} reached terminal syncStatus={got!r} (want {expected!r})")
            logger.info(f"VVR {name!r} syncStatus={got!r}, still waiting…")
            return False

        return wait(timeout, _check, sleep=10,
                    message=f"VVR {name!r} did not reach syncStatus={expected!r} within {timeout}s")

    def failover_to(self, name: str, new_primary_sc: str, namespace: str = "default") -> None:
        """Patch spec.primaryStorageClass to trigger a failover."""
        logger.info(f"Failing over VVR {name!r}: new primary SC = {new_primary_sc!r}")
        self.patch(name, {"spec": {"primaryStorageClass": new_primary_sc}}, namespace)

    def wait_failover_complete(
        self,
        name: str,
        expected_primary_sc: str,
        namespace: str = "default",
        timeout: int = 15 * MINUTE,
    ) -> None:
        """Block until the failover (or failback) is fully settled.

        ``wait_sync_status(SYNC_COMPLETED)`` alone is insufficient because right
        after ``failover_to()`` the VVR may still report ``Completed`` from the
        *previous* state before the controller has started processing the change.
        This method additionally checks ``currentPrimaryStorageClass`` so it only
        returns once the VAST side has actually completed the role transition.
        """
        logger.info(
            f"Waiting for VVR {name!r} to settle with primary={expected_primary_sc!r}"
        )

        def _check():
            obj = self.get(name, namespace)
            status = obj.get("status") or {}
            current = status.get("currentPrimaryStorageClass", "")
            sync = status.get("syncStatus", "")
            if current == expected_primary_sc and sync == SYNC_COMPLETED:
                return True
            if sync in _TERMINAL_SYNC_STATUSES:
                self.describe(name, namespace)
                raise Exception(
                    f"VVR {name!r} reached terminal syncStatus={sync!r} "
                    f"(want primary={expected_primary_sc!r})"
                )
            logger.info(
                f"VVR {name!r} currentPrimary={current!r} syncStatus={sync!r}, "
                f"waiting for primary={expected_primary_sc!r} and Completed…"
            )
            return False

        wait(
            timeout, _check, sleep=10,
            message=(
                f"VVR {name!r} did not settle with primary={expected_primary_sc!r} "
                f"within {timeout}s"
            ),
        )

    def current_primary_sc(self, name: str, namespace: str = "default") -> str:
        """Return status.currentPrimaryStorageClass (empty string when not yet set)."""
        obj = self.get(name, namespace)
        return (obj.get("status") or {}).get("currentPrimaryStorageClass", "")


class VastReplicationContent(KubernetesResource):
    """Manager for VastReplicationContent (vrc) custom resources.

    VRCs are owned by VVR/VSCR and deleted indirectly — tracked here only for
    post-deletion assertions (wait until all VRCs labelled by a given VVR/VSCR
    are fully gone, meaning operator cleanup has finished).
    """

    resource_type = "vastreplicationcontents"
    record_on_create = False

    def wait_all_gone(
        self,
        labels: dict,
        namespace: str = "default",
        timeout: int = 15 * MINUTE,
    ) -> None:
        """Block until no VRC objects with the given *labels* exist.

        Called after a VVR/VSCR is deleted to confirm the operator has finished
        cleaning up all per-cluster VastReplicationContent objects (and their
        associated VAST-side volumes) before we query the VAST REST API.
        """
        label_str = ", ".join(f"{k}={v}" for k, v in labels.items())
        logger.info(f"Waiting for all VastReplicationContent [{label_str}] to be gone")
        self.wait(
            timeout=timeout,
            labels=labels,
            namespace=namespace,
            condition="Deleted",
            error_msg=f"VastReplicationContent [{label_str}] not fully cleaned up within {timeout}s",
        )


class VastStorageClassReplication(KubernetesResource):
    """Manager for VastStorageClassReplication (vscr) custom resources."""

    resource_type = "vaststorageclassreplications"
    record_on_create = False  # cleaned up via add_cleanup; same rationale as VVR above

    def create(self, builder, record_on_create=None) -> object:
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)

    def wait_sync_status(
        self,
        name: str,
        expected: str,
        namespace: str = "default",
        timeout: int = 15 * MINUTE,
    ) -> object:
        """Block until status.syncStatus == expected or timeout."""
        logger.info(f"Waiting for VSCR {name!r} to reach syncStatus={expected!r}")

        def _check():
            obj = self.get(name, namespace)
            got = (obj.get("status") or {}).get("syncStatus", "")
            if got == expected:
                return obj
            if got in _TERMINAL_SYNC_STATUSES:
                self.describe(name, namespace)
                raise Exception(f"VSCR {name!r} reached terminal syncStatus={got!r} (want {expected!r})")
            logger.info(f"VSCR {name!r} syncStatus={got!r}, still waiting…")
            return False

        return wait(timeout, _check, sleep=10,
                    message=f"VSCR {name!r} did not reach syncStatus={expected!r} within {timeout}s")

    def failover_to(self, name: str, new_primary_sc: str, namespace: str = "default") -> None:
        """Patch spec.primaryStorageClass to trigger a failover."""
        logger.info(f"Failing over VSCR {name!r}: new primary SC = {new_primary_sc!r}")
        self.patch(name, {"spec": {"primaryStorageClass": new_primary_sc}}, namespace)

    def wait_failover_complete(
        self,
        name: str,
        expected_primary_sc: str,
        namespace: str = "default",
        timeout: int = 15 * MINUTE,
    ) -> None:
        """Block until the failover (or failback) is fully settled.

        Same rationale as ``VastVolumeReplication.wait_failover_complete``:
        checks both ``currentPrimaryStorageClass`` and ``syncStatus`` to avoid
        returning prematurely on a stale ``Completed`` value.
        """
        logger.info(
            f"Waiting for VSCR {name!r} to settle with primary={expected_primary_sc!r}"
        )

        def _check():
            obj = self.get(name, namespace)
            status = obj.get("status") or {}
            current = status.get("currentPrimaryStorageClass", "")
            sync = status.get("syncStatus", "")
            if current == expected_primary_sc and sync == SYNC_COMPLETED:
                return True
            if sync in _TERMINAL_SYNC_STATUSES:
                self.describe(name, namespace)
                raise Exception(
                    f"VSCR {name!r} reached terminal syncStatus={sync!r} "
                    f"(want primary={expected_primary_sc!r})"
                )
            logger.info(
                f"VSCR {name!r} currentPrimary={current!r} syncStatus={sync!r}, "
                f"waiting for primary={expected_primary_sc!r} and Completed…"
            )
            return False

        wait(
            timeout, _check, sleep=10,
            message=(
                f"VSCR {name!r} did not settle with primary={expected_primary_sc!r} "
                f"within {timeout}s"
            ),
        )

    def current_primary_sc(self, name: str, namespace: str = "default") -> str:
        """Return status.currentPrimaryStorageClass."""
        obj = self.get(name, namespace)
        return (obj.get("status") or {}).get("currentPrimaryStorageClass", "")
