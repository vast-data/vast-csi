"""Feature selection shared by e2e setup and test builders."""
from __future__ import annotations

from collections.abc import Iterable


class Features:
    """Immutable set of features enabled for a test session."""

    MTLS = "mtls"

    def __init__(self, enabled: Iterable[str] = ()) -> None:
        self._enabled = frozenset(enabled)

    def enabled(self, feature: str) -> bool:
        return feature in self._enabled

    def __contains__(self, feature: str) -> bool:
        return self.enabled(feature)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({sorted(self._enabled)!r})"
