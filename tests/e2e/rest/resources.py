"""Test-only mixins applied onto live VmsSession resource instances.

Do not subclass Quota/View/etc. ``E2EVmsSession`` rebinds each resource's
class to ``(TestResourceMixin, original_class)`` after construction so
``session.quotas`` / ``session.views`` keep their production API and gain
helpers used only by e2e.
"""
from __future__ import annotations

from typing import Any, Callable

from easypy.bunch import Bunch

from vast_csi.session.resources import VastResource


class TestRecord:
    """One VMS object (quota, view, …) with live lookups for test assertions."""

    def __init__(self, data: Any, resource: VastResource):
        self._data = data if isinstance(data, Bunch) else Bunch.from_dict(data)
        self._resource = resource

    def __getattr__(self, name: str):
        return getattr(self._data, name)

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, *args, **kwargs):
        return self._data.get(*args, **kwargs)

    def __repr__(self):
        name = self._data.get("name") or self._data.get("id")
        return f"<{type(self._resource).__name__} {name}>"

    def _refresh(self):
        rid = self._data.get("id")
        if rid is None:
            return None
        return self._resource.get(rid, fail_if_missing=False)

    @property
    def hard_limit(self):
        return self._data.get("hard_limit") or self._data.get("hard_limit_bytes") or 0

    @property
    def used_capacity(self):
        fresh = self._refresh()
        if fresh is None:
            return 0
        data = fresh._data if isinstance(fresh, TestRecord) else fresh
        return data.get("used_effective_capacity") or data.get("used_capacity") or 0

    @property
    def was_removed(self) -> bool:
        return self._refresh() is None

    @property
    def path(self):
        return self._data.get("path")


class TestResourceMixin:
    """Predicate helpers and iteration over ``list()`` for e2e tests."""

    def _wrap(self, item: Any):
        if item is None or isinstance(item, TestRecord):
            return item
        return TestRecord(item, self)

    def __iter__(self):
        return (self._wrap(item) for item in self.list())

    def __len__(self):
        return len(self.list())

    def single(self, pred: Callable[[Any], bool]):
        found = [item for item in self if pred(item)]
        return found[0] if found else None

    def choose(self, pred: Callable[[Any], bool]):
        found = self.single(pred)
        if found is None:
            raise LookupError(f"no matching {type(self).__name__} record")
        return found


_EXTENDED_CLASSES: dict[type, type] = {}


def extend_resource(resource: VastResource) -> VastResource:
    """Return the same instance data with TestResourceMixin methods mixed in.

    The dynamic class keeps the production name (``VipPool``, ``Quota``, …)
    so VMS error text still says ``vippool`` / ``quota``, not ``e2evippool``.
    """
    orig = type(resource)
    if issubclass(orig, TestResourceMixin):
        return resource
    cls = _EXTENDED_CLASSES.get(orig)
    if cls is None:
        cls = type(orig)(
            orig.__name__,
            (TestResourceMixin, orig),
            {"__module__": orig.__module__, "__qualname__": orig.__qualname__},
        )
        _EXTENDED_CLASSES[orig] = cls
    extended = cls.__new__(cls)
    extended.__dict__.update(resource.__dict__)
    return extended
