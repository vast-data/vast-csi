"""Builders for COSI (Container Object Storage Interface) manifests."""
from __future__ import annotations

from typing import Any, Optional

from lib.builders.base import Builder, resource_name


class BucketClaimBuilder(Builder):
    @classmethod
    def new(cls, *, name: Optional[str] = None, bucket_class_name: str) -> "BucketClaimBuilder":
        body: dict[str, Any] = {
            "apiVersion": "objectstorage.k8s.io/v1alpha1",
            "kind": "BucketClaim",
            "metadata": {"name": resource_name("bucketclaim", name)},
            "spec": {"bucketClassName": bucket_class_name, "protocols": ["s3"]},
        }
        return cls._from_body(body)


class BucketAccessClassBuilder(Builder):
    @classmethod
    def new(cls, *, name: Optional[str] = None) -> "BucketAccessClassBuilder":
        body: dict[str, Any] = {
            "apiVersion": "objectstorage.k8s.io/v1alpha1",
            "kind": "BucketAccessClass",
            "metadata": {"name": resource_name("bucketaccessclass", name)},
            "driverName": "csi.vastdata.com",
            "authenticationType": "KEY",
        }
        return cls._from_body(body)


class BucketAccessBuilder(Builder):
    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        bucket_name: str,
        bucket_access_class_name: str,
        secret_name: str,
    ) -> "BucketAccessBuilder":
        body: dict[str, Any] = {
            "apiVersion": "objectstorage.k8s.io/v1alpha1",
            "kind": "BucketAccess",
            "metadata": {"name": resource_name("bucketaccess", name)},
            "spec": {
                "bucketClaimName": bucket_name,
                "bucketAccessClassName": bucket_access_class_name,
                "credentialsSecretName": secret_name,
            },
        }
        return cls._from_body(body)
