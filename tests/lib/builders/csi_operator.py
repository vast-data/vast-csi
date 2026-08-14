"""Builders for VAST CRD manifests: VastCSIDriver, VastCluster, VastStorage."""
from __future__ import annotations

from typing import Any, Optional

from lib.builders.base import Builder, resource_name
from lib.constants import CSI_NAMESPACE, PASSWORD, ROOT_EXPORT, USERNAME


class VastCSIDriverBuilder(Builder):
    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        namespace: str = CSI_NAMESPACE,
        driver_type: str = "nfs",
    ) -> "VastCSIDriverBuilder":
        body: dict[str, Any] = {
            "apiVersion": "storage.vastdata.com/v1",
            "kind": "VastCSIDriver",
            "metadata": {"name": resource_name("vastcsidriver", name), "namespace": namespace},
            "spec": {} if driver_type == "nfs" else {"driverType": driver_type},
        }
        return cls._from_body(body)

    def with_operation_timeout(self, seconds: int) -> "VastCSIDriverBuilder":
        self._body.setdefault("spec", {})["operationTimeout"] = seconds
        return self

    def with_deletion_resources(self, vip_pool: str, view_policy: str) -> "VastCSIDriverBuilder":
        """Fallback for volume delete when Trash API is unavailable (matches helm e2e defaults)."""
        self._body.setdefault("spec", {}).update({
            "deletionVipPool": vip_pool,
            "deletionViewPolicy": view_policy,
        })
        return self


class VastClusterBuilder(Builder):
    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        endpoint: str,
        namespace: str = CSI_NAMESPACE,
        username: str = USERNAME,
        password: str = PASSWORD,
    ) -> "VastClusterBuilder":
        body: dict[str, Any] = {
            "apiVersion": "storage.vastdata.com/v1",
            "kind": "VastCluster",
            "metadata": {"name": resource_name("vastcluster", name), "namespace": namespace},
            "spec": {"endpoint": endpoint, "username": username, "password": password},
        }
        return cls._from_body(body)


class VastStorageBuilder(Builder):
    """
    builder for VastStorage CRD.

    Driver type is inferred from which ``with_*`` call is used:
    - ``with_filesystem(view_policy=...)`` → NFS driver
    - ``with_block(subsystem=...)``        → NVMe-oF block driver
    """

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        vast_cluster_name: str,
        vip_pool: str,
        provisioner: str,
        namespace: str = CSI_NAMESPACE,
    ) -> "VastStorageBuilder":
        body: dict[str, Any] = {
            "apiVersion": "storage.vastdata.com/v1",
            "kind": "VastStorage",
            "metadata": {"name": resource_name("vaststorage", name), "namespace": namespace},
            "spec": {
                "provisioner": provisioner,
                "clusterName": vast_cluster_name,
                "vipPool": vip_pool,
                "createSnapshotClass": True,
                "setDefaultStorageClass": True,
            },
        }
        return cls._from_body(body)

    def with_filesystem(
        self,
        *,
        view_policy: Optional[str],
        storage_path: str = ROOT_EXPORT,
    ) -> "VastStorageBuilder":
        if view_policy is None:
            return self
        self._body["spec"].update({"viewPolicy": view_policy, "storagePath": storage_path})
        return self

    def with_block(
        self,
        *,
        subsystem: Optional[str],
        blocking_clones: Optional[bool] = None,
    ) -> "VastStorageBuilder":
        if subsystem is None:
            return self
        self._body["spec"].update({
            "subsystem": subsystem,
            "driverType": "block",
            "storagePath": subsystem,
        })
        if blocking_clones is not None:
            self._body["spec"]["blockingClones"] = blocking_clones
        return self

    def with_snapshot_class(
        self,
        enabled: bool,
        snapshot_name_format: str = "csi:{namespace}:{name}:{id}",
    ) -> "VastStorageBuilder":
        self._body["spec"]["createSnapshotClass"] = enabled
        if enabled:
            self._body["spec"]["snapshotClass"] = {
                "setDefaultSnapshotClass": True,
                "snapshotNameFormat": snapshot_name_format,
                "deletionPolicy": "Delete",
            }
        return self

    def with_volume_name_format(self, fmt: str) -> "VastStorageBuilder":
        self._body["spec"]["volumeNameFormat"] = fmt
        return self

    def with_ephemeral_volume_name_format(self, fmt: str) -> "VastStorageBuilder":
        self._body["spec"]["ephemeralVolumeNameFormat"] = fmt
        return self

    def with_mount_options(self, options: list[str]) -> "VastStorageBuilder":
        self._body["spec"]["mountOptions"] = list(options)
        return self

    def with_blocking_clones(self, enabled: bool = True) -> "VastStorageBuilder":
        self._body["spec"]["blockingClones"] = enabled
        return self

    def with_snapshot_name_format(self, fmt: str) -> "VastStorageBuilder":
        self._body["spec"].setdefault("snapshotClass", {})["snapshotNameFormat"] = fmt
        return self
