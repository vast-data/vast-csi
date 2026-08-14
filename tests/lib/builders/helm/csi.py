"""Helm values builder for the vastcsi chart."""
from __future__ import annotations

from typing import Any, Self

from lib.builders.helm.base import HelmValuesBuilder, secret_fields, vippool_fields
from lib.constants import CSI_NAMESPACE, NFS_MOUNT_OPTIONS, PASSWORD, ROOT_EXPORT, SNAPSHOT_CLASS, USERNAME, VIEW_POLICY_NAME, VIPPOOL_NAME, nfs_storage_class


class VastCsiHelmValuesBuilder(HelmValuesBuilder):
    @classmethod
    def for_fleet(cls, system, *, namespace: str = CSI_NAMESPACE) -> Self:
        return (
            cls.new()
            .with_auth(
                username=USERNAME,
                password=PASSWORD,
                endpoint=system.endpoint,
            )
            .with_deletion_resources(VIPPOOL_NAME, VIEW_POLICY_NAME)
            .with_attach_required(True)
            .with_nfs_services(True)
            .with_nfs_mount_options()
            .with_storage_classes(namespace=namespace)
            .with_snapshot_classes(namespace=namespace)
        )

    def with_deletion_resources(self, vip_pool: str, view_policy: str) -> Self:
        self._values["deletionVipPool"] = vip_pool
        self._values["deletionViewPolicy"] = view_policy
        return self

    def with_attach_required(self, required: bool | str = True) -> Self:
        value = str(required).lower() if isinstance(required, bool) else required
        self._values["attachRequired"] = value
        return self

    def with_force_lazy_umount_on_timeout(self, enabled: bool = True) -> Self:
        self._values["forceLazyUmountOnTimeout"] = enabled
        return self

    def with_nfs_services(
        self,
        enabled: bool = True,
        *,
        services: list[str] | None = None,
        persist_statd: bool = False,
    ) -> Self:
        """Enable the in-container NFS client-services sidecar (rpcbind/statd/...).

        Safe on hosts that already provide these daemons: each process starts
        only if the host does not already expose it.
        """
        nfs = self._values.setdefault("node", {}).setdefault("nfsServices", {})
        nfs["enabled"] = enabled
        if services is not None:
            nfs["services"] = list(services)
        nfs["persistStatd"] = persist_statd
        return self

    def with_nfs_mount_options(self, options: list[str] | None = None) -> Self:
        """Force NFSv4.1 on every NFS StorageClass (never NFSv3 in e2e)."""
        self._values.setdefault("storageClassDefaults", {})["mountOptions"] = list(
            options or NFS_MOUNT_OPTIONS
        )
        return self

    def with_storage_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("storageClasses", {})[name] = options
        return self

    def with_storage_classes(self, *, namespace: str = CSI_NAMESPACE) -> Self:
        storage_classes = self._values.setdefault("storageClasses", {})
        storage_classes[nfs_storage_class(0)] = self._nfs_sc_params(namespace)
        storage_classes[nfs_storage_class(1)] = self._nfs_sc_params(
            namespace, extra=True,
        )
        return self

    @staticmethod
    def _nfs_sc_params(namespace: str, *, extra: bool = False) -> dict[str, Any]:
        params = {
            "storagePath": ROOT_EXPORT if not extra else f"{ROOT_EXPORT.rstrip('/')}-1",
            "viewPolicy": VIEW_POLICY_NAME,
            "mountOptions": list(NFS_MOUNT_OPTIONS),
            **vippool_fields(VIPPOOL_NAME),
            **secret_fields(namespace),
        }
        if extra:
            params["reclaimPolicy"] = "Retain"
            params["volumeNameFormat"] = "csi:2:{name}:{id}"
        return params

    def with_snapshot_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("snapshotClasses", {})[name] = options
        return self

    def with_snapshot_classes(self, *, namespace: str = CSI_NAMESPACE) -> Self:
        self._values.setdefault("snapshotClasses", {})[SNAPSHOT_CLASS] = secret_fields(namespace)
        return self
