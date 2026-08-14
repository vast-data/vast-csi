"""
builder for Kubernetes manifest dicts.

Usage::

    from e2e.builders.storage import PVCBuilder

    manifest = (
        PVCBuilder.new(access_modes=["ReadWriteOnce"], storage_class_name="sc")
        .with_labels(app="myapp")
        .result()
    )
    k8s.pvcs.apply([manifest])
"""
from __future__ import annotations

import copy
from typing import Any, Optional, Self

from easypy.bunch import Bunch
from easypy.random import random_nice_name


def resource_name(kind: str, name: Optional[str] = None, *, max_length: int = 63) -> str:
    """Return *name* or ``{kind}-{random_nice_name}`` (DNS-1123 label, max 63 chars)."""
    if name:
        return name
    prefix = f"{kind}-"
    suffix_budget = max_length - len(prefix)
    if suffix_budget < 1:
        raise ValueError(f"kind {kind!r} too long for max_length {max_length}")
    return f"{prefix}{random_nice_name(max_length=suffix_budget)}"


class Builder:
    """
    Generic builder that produces a Bunch manifest.

    Subclasses implement ``new(...)`` class-methods that call
    ``cls._from_body(body)`` with a pre-populated dict, then expose
    domain-specific ``with_*`` chaining methods.

    Terminal operation: ``.result()`` returns a deep-copied Bunch.
    """

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    @property
    def name(self) -> str:
        return self._body["metadata"]["name"]

    @classmethod
    def _from_body(cls, body: dict[str, Any]) -> "Builder":
        return cls(body)

    def with_labels(self, **labels: str) -> Self:
        self._body.setdefault("metadata", {}).setdefault("labels", {}).update(labels)
        return self

    def with_annotations(self, **annotations: str) -> Self:
        self._body.setdefault("metadata", {}).setdefault("annotations", {}).update(annotations)
        return self

    def with_namespace(self, namespace: str) -> Self:
        self._body.setdefault("metadata", {})["namespace"] = namespace
        return self

    def with_spec(self, **fields: Any) -> Self:
        self._body.setdefault("spec", {}).update(fields)
        return self

    def result(self) -> Bunch:
        """Return a deep-copied Bunch of the manifest body."""
        return Bunch.from_dict(copy.deepcopy(self._body))
