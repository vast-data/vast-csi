"""Builders for VastVolumeReplication and VastStorageClassReplication manifests."""
from __future__ import annotations

from typing import Any, List, Optional

from e2e.builders.base import Builder, resource_name

_API_VERSION = "vastdata.com/v1alpha1"

# Default protection-policy schedule used across tests — frequent enough for CI.
_DEFAULT_POLICY = {"params": [{"every": "15m", "keepLocal": "2d", "keepRemote": "7d"}]}


class VastVolumeReplicationBuilder(Builder):
    """Fluent builder for a VastVolumeReplication (VVR) manifest.

    Example::

        vvr = (
            VastVolumeReplicationBuilder.new(
                name="my-vvr",
                volume_name="my-pvc",
                primary_storage_class="vastdata-filesystem-site-a",
                protection_topology=[
                    {"source": "vastdata-filesystem-site-a",
                     "destination": "vastdata-filesystem-site-b"},
                ],
            )
        )
        k8s.vvrs.create(vvr)
    """

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        namespace: str = "default",
        volume_name: str,
        primary_storage_class: str,
        protection_topology: List[dict],
        sync_interval_seconds: int = 900,
        failover_type: str = "ungracefulFailover",
        pvc_remap: bool = True,
        dest_vol_reclaim_policy: Optional[str] = None,
    ) -> "VastVolumeReplicationBuilder":
        body: dict[str, Any] = {
            "apiVersion": _API_VERSION,
            "kind": "VastVolumeReplication",
            "metadata": {
                "name": resource_name("vvr", name),
                "namespace": namespace,
            },
            "spec": {
                "volumeName": volume_name,
                "primaryStorageClass": primary_storage_class,
                "protectionTopology": protection_topology,
                "syncIntervalSeconds": sync_interval_seconds,
                "failoverType": failover_type,
                "pvcRemap": pvc_remap,
                "protectionPolicyTemplate": _DEFAULT_POLICY,
            },
        }
        if dest_vol_reclaim_policy is not None:
            body["spec"]["destVolReclaimPolicy"] = dest_vol_reclaim_policy
        return cls._from_body(body)

    def with_primary_storage_class(self, sc: str) -> "VastVolumeReplicationBuilder":
        self._body["spec"]["primaryStorageClass"] = sc
        return self

    def with_failover_type(self, failover_type: str) -> "VastVolumeReplicationBuilder":
        self._body["spec"]["failoverType"] = failover_type
        return self

    def with_dest_vol_reclaim_policy(self, policy: str) -> "VastVolumeReplicationBuilder":
        self._body["spec"]["destVolReclaimPolicy"] = policy
        return self

    def with_protection_policy(
        self, every: str, keep_local: str, keep_remote: str
    ) -> "VastVolumeReplicationBuilder":
        self._body["spec"]["protectionPolicyTemplate"] = {
            "params": [{"every": every, "keepLocal": keep_local, "keepRemote": keep_remote}]
        }
        return self


class VastStorageClassReplicationBuilder(Builder):
    """Fluent builder for a VastStorageClassReplication (VSCR) manifest.

    Example::

        vscr = (
            VastStorageClassReplicationBuilder.new(
                name="my-vscr",
                primary_storage_class="vastdata-filesystem-site-a",
                protection_topology=[
                    {"source": "vastdata-filesystem-site-a",
                     "destination": "vastdata-filesystem-site-b"},
                ],
            )
        )
        k8s.vscrs.create(vscr)
    """

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        namespace: str = "default",
        primary_storage_class: str,
        protection_topology: List[dict],
        sync_interval_seconds: int = 900,
        failover_type: str = "ungracefulFailover",
        sync_pvc_pv: bool = True,
        pvc_remap: bool = True,
        dest_vol_reclaim_policy: Optional[str] = None,
    ) -> "VastStorageClassReplicationBuilder":
        body: dict[str, Any] = {
            "apiVersion": _API_VERSION,
            "kind": "VastStorageClassReplication",
            "metadata": {
                "name": resource_name("vscr", name),
                "namespace": namespace,
            },
            "spec": {
                "primaryStorageClass": primary_storage_class,
                "protectionTopology": protection_topology,
                "syncIntervalSeconds": sync_interval_seconds,
                "failoverType": failover_type,
                "syncPVCPV": sync_pvc_pv,
                "pvcRemap": pvc_remap,
                "protectionPolicyTemplate": _DEFAULT_POLICY,
            },
        }
        if dest_vol_reclaim_policy is not None:
            body["spec"]["destVolReclaimPolicy"] = dest_vol_reclaim_policy
        return cls._from_body(body)

    def with_primary_storage_class(self, sc: str) -> "VastStorageClassReplicationBuilder":
        self._body["spec"]["primaryStorageClass"] = sc
        return self

    def with_failover_type(self, failover_type: str) -> "VastStorageClassReplicationBuilder":
        self._body["spec"]["failoverType"] = failover_type
        return self

    def with_dest_vol_reclaim_policy(self, policy: str) -> "VastStorageClassReplicationBuilder":
        self._body["spec"]["destVolReclaimPolicy"] = policy
        return self
