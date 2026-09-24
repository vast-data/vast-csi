"""Builders for ConfigMap and Secret manifests."""
from __future__ import annotations

from typing import Self

from lib.builders.base import Builder, resource_name


class ConfigMapBuilder(Builder):
    """Fluent builder for a Kubernetes ConfigMap."""

    @classmethod
    def new(cls, *, name: str | None = None) -> Self:
        return cls._from_body({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": resource_name("configmap", name)},
        })

    def with_data(self, key: str, value: str) -> Self:
        self._body.setdefault("data", {})[key] = value
        return self

    def with_binary_data(self, key: str, base64_value: str) -> Self:
        self._body.setdefault("binaryData", {})[key] = base64_value
        return self

    def immutable(self, enabled: bool = True) -> Self:
        self._body["immutable"] = enabled
        return self


class SecretBuilder(Builder):
    """Fluent builder for a Kubernetes Secret."""

    @classmethod
    def new(
        cls,
        *,
        name: str | None = None,
        secret_type: str = "Opaque",
    ) -> Self:
        return cls._from_body({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": resource_name("secret", name)},
            "type": secret_type,
        })

    def with_string_data(self, key: str, value: str) -> Self:
        self._body.setdefault("stringData", {})[key] = value
        return self

    def with_data(self, key: str, base64_value: str) -> Self:
        self._body.setdefault("data", {})[key] = base64_value
        return self

    def immutable(self, enabled: bool = True) -> Self:
        self._body["immutable"] = enabled
        return self
