"""Builders for PVC, StorageClass, and VolumeSnapshot manifests."""
from __future__ import annotations

from typing import Any, List, Optional

from lib.builders.base import Builder, resource_name
from lib.constants import CSI_NAMESPACE, NFS_MOUNT_OPTIONS, ROOT_EXPORT, VIEW_POLICY_NAME


class PVCBuilder(Builder):
    """builder for a PersistentVolumeClaim manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        access_modes: List[str],
        storage_class_name: str,
        storage: str = "1Gi",
    ) -> "PVCBuilder":
        body: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": resource_name("pvc", name)},
            "spec": {
                "accessModes": access_modes,
                "storageClassName": storage_class_name,
                "resources": {"requests": {"storage": storage}},
            },
        }
        return cls._from_body(body)

    def with_data_source(self, name: str, kind: str, apiGroup: str = "") -> "PVCBuilder":
        self._body["spec"]["dataSource"] = {"name": name, "kind": kind, "apiGroup": apiGroup}
        return self

    def with_volume_name(self, pv_name: str) -> "PVCBuilder":
        self._body["spec"]["volumeName"] = pv_name
        return self

    def with_volume_mode(self, volume_mode: str) -> "PVCBuilder":
        self._body["spec"]["volumeMode"] = volume_mode
        return self


class StorageClassBuilder(Builder):
    """builder for a StorageClass manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        vip_pool_name: str,
    ) -> "StorageClassBuilder":
        body: dict[str, Any] = {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {"name": resource_name("storageclass", name)},
            "provisioner": "csi.vastdata.com",
            "reclaimPolicy": "Delete",
            "mountOptions": list(NFS_MOUNT_OPTIONS),
            "parameters": {
                "root_export": ROOT_EXPORT,
                "view_policy": VIEW_POLICY_NAME,
                "vip_pool_name": vip_pool_name,
                "volume_name_fmt": "csi:2:{name}:{id}",
                "lb_strategy": "roundrobin",
                "clone_background_sync": "true",
            },
        }
        return cls._from_body(body)

    def with_root_export(self, root_export: str) -> "StorageClassBuilder":
        self._body["parameters"]["root_export"] = root_export
        return self

    def with_view_policy(self, view_policy: str) -> "StorageClassBuilder":
        self._body["parameters"]["view_policy"] = view_policy
        return self

    def with_reclaim_policy(self, policy: str) -> "StorageClassBuilder":
        self._body["reclaimPolicy"] = policy
        return self

    def with_mount_options(self, options: str) -> "StorageClassBuilder":
        extra = [o.strip() for o in options.split(",") if o.strip()]
        self._body["mountOptions"] = list(dict.fromkeys([*NFS_MOUNT_OPTIONS, *extra]))
        return self

    def with_vip_pool_fqdn_random_prefix(self, enabled: bool) -> "StorageClassBuilder":
        self._body["parameters"]["vip_pool_fqdn_random_prefix"] = "true" if enabled else "false"
        return self

    def with_clone_background_sync(self, value: str) -> "StorageClassBuilder":
        self._body["parameters"]["clone_background_sync"] = value
        return self

    def with_secret(self, secret_name: Optional[str]) -> "StorageClassBuilder":
        if not secret_name:
            return self
        params = self._body["parameters"]
        for key, ns_key in (
            ("provisioner-secret-name",         "provisioner-secret-namespace"),
            ("controller-publish-secret-name",   "controller-publish-secret-namespace"),
            ("node-publish-secret-name",         "node-publish-secret-namespace"),
            ("controller-expand-secret-name",    "controller-expand-secret-namespace"),
        ):
            params[f"csi.storage.k8s.io/{key}"] = secret_name
            params[f"csi.storage.k8s.io/{ns_key}"] = CSI_NAMESPACE
        return self


class VolumeSnapshotBuilder(Builder):
    """Fluent builder for a VolumeSnapshot manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        pvc_name: str,
        snapshot_class_name: str,
    ) -> "VolumeSnapshotBuilder":
        body: dict[str, Any] = {
            "apiVersion": "snapshot.storage.k8s.io/v1",
            "kind": "VolumeSnapshot",
            "metadata": {"name": resource_name("volumesnapshot", name)},
            "spec": {
                "source": {"persistentVolumeClaimName": pvc_name},
                "volumeSnapshotClassName": snapshot_class_name,
            },
        }
        return cls._from_body(body)
