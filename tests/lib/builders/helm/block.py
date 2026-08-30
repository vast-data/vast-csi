"""Helm values builder for the vastblock chart."""
from __future__ import annotations

from typing import Any, Self

from lib.builders.helm.base import HelmValuesBuilder, secret_fields
from lib.constants import (
    BLOCK_STORAGE_CLASS,
    BLOCK_SUBSYSTEM,
    CSI_NAMESPACE,
    PASSWORD,
    SNAPSHOT_CLASS,
    USERNAME,
    VIPPOOL_NAME,
    numbered_name,
)


class VastBlockHelmValuesBuilder(HelmValuesBuilder):
    @classmethod
    def for_fleet(cls, system, *, namespace: str = CSI_NAMESPACE) -> Self:
        return (
            cls.new()
            .with_auth(
                username=USERNAME,
                password=PASSWORD,
                endpoint=system.endpoint,
            )
            .with_attach_required(True)
            .with_storage_class_defaults(blockingClones=True)
            .with_storage_classes(namespace=namespace)
            .with_snapshot_classes(namespace=namespace)
        )

    def with_storage_class_defaults(self, **kwargs: Any) -> Self:
        normalized = {
            k: str(v).lower() if isinstance(v, bool) else v
            for k, v in kwargs.items()
        }
        self._values.setdefault("storageClassDefaults", {}).update(normalized)
        return self

    def with_attach_required(self, required: bool | str = True) -> Self:
        value = str(required).lower() if isinstance(required, bool) else required
        self._values["attachRequired"] = value
        return self

    def with_force_lazy_umount_on_timeout(self, enabled: bool = True) -> Self:
        self._values["forceLazyUmountOnTimeout"] = enabled
        return self

    def with_storage_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("storageClasses", {})[name] = {
            "subsystem": BLOCK_SUBSYSTEM,
            **options,
        }
        return self

    def with_storage_classes(self, *, namespace: str = CSI_NAMESPACE) -> Self:
        storage_classes = self._values.setdefault("storageClasses", {})
        self._add_block_sc_group(storage_classes, 0, namespace)
        self._add_block_sc_group(storage_classes, 1, namespace)
        return self

    def _add_block_sc_group(
        self,
        storage_classes: dict,
        index: int,
        namespace: str,
    ) -> None:
        base = {
            "subsystem": BLOCK_SUBSYSTEM,
            "vipPool": VIPPOOL_NAME,
            **secret_fields(namespace),
        }
        sc_name = numbered_name(BLOCK_STORAGE_CLASS, index)
        storage_classes[sc_name] = base
        storage_classes[f"{sc_name}-xfs"]  = {
            **base, "fsType": "xfs",
            "formatOptions": ["-d", "agsize=1g"],
        }
        storage_classes[f"{sc_name}-ext3"] = {**base, "fsType": "ext3"}

    def with_snapshot_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("snapshotClasses", {})[name] = options
        return self

    def with_snapshot_classes(self, *, namespace: str = CSI_NAMESPACE) -> Self:
        self._values.setdefault("snapshotClasses", {})[SNAPSHOT_CLASS] = secret_fields(namespace)
        return self
