"""Builders for COSI (Container Object Storage Interface) manifests."""
from __future__ import annotations

import json
from typing import Any, Optional

from lib.builders.base import Builder, resource_name

_ANNOTATION_PREFIX = "cosi.vastdata.com/"
ANNOTATION_FLATTEN = f"{_ANNOTATION_PREFIX}flatten-credentials"
ANNOTATION_MAX_SIZE = f"{_ANNOTATION_PREFIX}maxSize"
ANNOTATION_SOURCE_BUCKET = f"{_ANNOTATION_PREFIX}sourceBucket"
ANNOTATION_BLOCKING_CLONES = f"{_ANNOTATION_PREFIX}blockingClones"


class BucketClassBuilder(Builder):
    """Cluster-scoped BucketClass."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        driver_name: str = "csi.vastdata.com",
        deletion_policy: str = "Delete",
        **parameters: Any,
    ) -> "BucketClassBuilder":
        body: dict[str, Any] = {
            "apiVersion": "objectstorage.k8s.io/v1alpha1",
            "kind": "BucketClass",
            "metadata": {"name": resource_name("bucketclass", name)},
            "driverName": driver_name,
            "deletionPolicy": deletion_policy,
            "parameters": {k: str(v) if not isinstance(v, str) else v for k, v in parameters.items()},
        }
        return cls._from_body(body)

    def with_parameters(self, **parameters: Any) -> "BucketClassBuilder":
        params = self._body.setdefault("parameters", {})
        for key, value in parameters.items():
            if isinstance(value, (dict, list)):
                params[key] = json.dumps(value)
            else:
                params[key] = str(value) if not isinstance(value, str) else value
        return self

    def with_lifecycle_rules(self, rules: list[dict]) -> "BucketClassBuilder":
        return self.with_parameters(lifecycle_rules=json.dumps(rules))

    def with_max_size(self, size: str) -> "BucketClassBuilder":
        return self.with_parameters(max_size=size)


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

    def with_max_size(self, size: str) -> "BucketClaimBuilder":
        return self.with_annotations(**{ANNOTATION_MAX_SIZE: size})

    def with_source_bucket(self, bucket_name: str, *, blocking: bool = True) -> "BucketClaimBuilder":
        anns = {ANNOTATION_SOURCE_BUCKET: bucket_name}
        if blocking:
            anns[ANNOTATION_BLOCKING_CLONES] = "true"
        return self.with_annotations(**anns)


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

    def with_credentials_secret(
        self, secret_name: str, *, namespace: Optional[str] = None
    ) -> "BucketAccessClassBuilder":
        params = self._body.setdefault("parameters", {})
        params["credentialsSecretName"] = secret_name
        if namespace:
            params["credentialsSecretNamespace"] = namespace
        return self


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

    def with_flatten_credentials(self) -> "BucketAccessBuilder":
        return self.with_annotations(**{ANNOTATION_FLATTEN: "true"})
