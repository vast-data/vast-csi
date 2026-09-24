"""Helm values builder for the vastcosi chart."""
from __future__ import annotations

from typing import Any, Self

from lib.builders.helm.base import HelmValuesBuilder
from lib.constants import PASSWORD, S3_POLICY_NAME, USERNAME, VIEW_POLICY_NAME, VIPPOOL_NAME


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
                vip_pool=VIPPOOL_NAME,
                view_policy=VIEW_POLICY_NAME,
            )
            .with_bucket_class(
                default_bucket_name,
                storagePath=bucket_storage_path,
                viewPolicy=S3_POLICY_NAME,
                vipPool=VIPPOOL_NAME,
            )
        )

    def with_bucket_class_defaults(
        self,
        *,
        storage_path: str,
        vip_pool: str,
        view_policy: str,
    ) -> Self:
        self._values.setdefault("bucketClassDefaults", {}).update({
            "storagePath": storage_path,
            "vipPool": vip_pool,
            "viewPolicy": view_policy,
        })
        return self

    def with_bucket_class(self, name: str, **options: Any) -> Self:
        self._values.setdefault("bucketClasses", {})[name] = options
        return self
