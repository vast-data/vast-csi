"""builders for helm chart subst_values dicts."""
from __future__ import annotations

import copy
from typing import Any, Self

from lib.constants import MGMT_SECRET


class HelmValuesBuilder:
    """
    Base fluent builder for helm ``subst_values`` dicts consumed by ``HelmValues.Chart``.

    Nested chart keys (``image.csiVastPlugin``, ``bucketClassDefaults``) are
    written as nested dicts so helm ``-f`` overlays merge correctly.

    Terminal operation: ``.result()`` returns a deep-copied dict.
    """

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self._values: dict[str, Any] = values or {}

    @classmethod
    def new(cls) -> Self:
        return cls()

    # ------------------------------------------------------------------
    # Common chart values
    # ------------------------------------------------------------------

    def with_auth(
        self,
        *,
        username: str,
        password: str,
        endpoint: str,
        secret_name: str = "vast-mgmt",
    ) -> Self:
        self._values.update({
            "username": username,
            "password": password,
            "endpoint": endpoint,
            "secretName": secret_name,
        })
        return self

    def with_image(self, repository: str, tag: str) -> Self:
        plugin = self._values.setdefault("image", {}).setdefault("csiVastPlugin", {})
        plugin["repository"] = repository
        plugin["tag"] = tag
        return self

    def with_image_pull_secrets(self, *names: str) -> Self:
        self._values["imagePullSecrets"] = [{"name": name} for name in names]
        return self

    def with_verify_ssl(self, enabled: bool) -> Self:
        self._values["verifySsl"] = enabled
        return self

    def set(self, key: str, value: Any) -> Self:
        self._values[key] = value
        return self

    def update(self, **values: Any) -> Self:
        self._values.update(values)
        return self

    def merge(self, other: dict[str, Any] | HelmValuesBuilder) -> Self:
        if isinstance(other, HelmValuesBuilder):
            other = other._values
        self._values.update(copy.deepcopy(other))
        return self

    # ------------------------------------------------------------------
    # Terminal operation
    # ------------------------------------------------------------------

    def result(self) -> dict[str, Any]:
        return copy.deepcopy(self._values)


def vippool_fields(vip_pool: str) -> dict[str, str]:
    return {"vipPool": vip_pool}


def secret_fields(namespace: str) -> dict[str, str]:
    return {
        "secretName": MGMT_SECRET,
        "secretNamespace": namespace,
    }
