"""Helm values builder for the vastcosi chart."""
from __future__ import annotations

from typing import Any, Self

from e2e.builders.helm.base import HelmValuesBuilder
from e2e.constants import PASSWORD, USERNAME


class VastCosiHelmValuesBuilder(HelmValuesBuilder):
    @classmethod
    def for_fleet(
        cls,
        system,
        *,
        bucket_storage_path: str = "/buckets",
        default_bucket_name: str = "vastdata-bucket",
    ) -> Self:
        return (
            cls.new()
            .with_auth(
                username=USERNAME,
                password=PASSWORD,
                endpoint=system.endpoint,
            )
            .with_bucket_class_defaults(
                storage_path=bucket_storage_path,
                vip_pool=system.vippool_name,
                view_policy=system.view_policy_name,
            )
            .with_bucket_class(
                default_bucket_name,
                viewPolicy=system.s3_policy_name,
                vipPool=system.vippool_name,
            )
        )

    def with_bucket_class_defaults(
        self,
        *,
        storage_path: str,
        vip_pool: str,
        view_policy: str,
    ) -> Self:
        self._values.update({
            "bucketClassDefaults.storagePath": storage_path,
            "bucketClassDefaults.vipPool": vip_pool,
            "bucketClassDefaults.viewPolicy": view_policy,
        })
        return self

    def with_bucket_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("bucketClasses", {})[name] = options
        return self
