"""
VMS async task (VTask) wait helpers with backoff polling and PVC-scoped retry tracking.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from easypy.bunch import bunchify
from easypy.sync import wait
from easypy.resilience import resilient as easypy_resilient
from urllib3.exceptions import MaxRetryError, ReadTimeoutError, TimeoutError
from requests.exceptions import ConnectionError

from ..logging import logger
from ..exceptions import TaskFailed

if TYPE_CHECKING:
    from .vms_session import VmsSession

POLL_INTERVAL_MIN = 2.0
POLL_INTERVAL_MAX = 10.0
# Extra initial delay per Kubernetes re-try on the same PVC/volume id
RETRY_EXTRA_MIN = 2.0
RETRY_CACHE_TTL = 120.0


@dataclass
class _RetryEntry:
    attempts: int = 0
    last_seen: float = 0.0


class VtaskRetryCache:
    """
    Process-wide retry counter keyed by PVC / CSI volume id.

    Entries not bumped within *ttl_seconds* are dropped on the next ``bump``
    so abandoned volume ids do not accumulate.
    """

    def __init__(self, ttl_seconds: float = RETRY_CACHE_TTL):
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._entries: dict[str, _RetryEntry] = {}

    def _prune_locked(self, now: float) -> None:
        stale = [
            key for key, entry in self._entries.items()
            if now - entry.last_seen > self._ttl
        ]
        for key in stale:
            del self._entries[key]

    def bump(self, retry_key: str) -> int:
        """Record a wait_task attempt for *retry_key*; return 1-based attempt number."""
        now = time.monotonic()
        with self._lock:
            self._prune_locked(now)
            entry = self._entries.get(retry_key)
            if entry is None:
                entry = _RetryEntry()
                self._entries[retry_key] = entry
            entry.attempts += 1
            entry.last_seen = now
            return entry.attempts


# Shared across gRPC workers in the controller process.
VTASK_RETRY_CACHE = VtaskRetryCache(ttl_seconds=RETRY_CACHE_TTL)


def task_poll_key(task: Any) -> Any:
    """Stable key for per-task VTask poll jitter (id, name, or request payload)."""
    if isinstance(task, int):
        return task
    if isinstance(task, dict):
        async_task = task.get("async_task", task)
        if isinstance(async_task, dict):
            return async_task.get("id") or async_task.get("name") or repr(task)
        return async_task
    return task


def vtask_poll_sleep(
    task_key: Any,
    sleep: float | None = None,
    *,
    attempt: int = 1,
) -> float | tuple[float, float]:
    """
    easypy ``wait`` sleep spec: exponential backoff from *first* to *max*, with
    per-task-key jitter on the initial interval.

    *attempt* > 1 adds extra delay on the first poll (Kubernetes re-tries).
    """
    min_iv = float(sleep if sleep is not None else POLL_INTERVAL_MIN)
    if attempt > 1:
        min_iv += (attempt - 1) * RETRY_EXTRA_MIN
    max_iv = float(max(min_iv, POLL_INTERVAL_MAX))
    if min_iv >= max_iv:
        return min_iv
    jitter_span = min(max_iv - min_iv, min_iv)
    offset = 0.0
    if task_key is not None:
        offset = (hash(task_key) % 1000) / 1000.0 * jitter_span
    return (min_iv + offset, max_iv)


def wait_task(
    session: "VmsSession",
    task,
    latest: bool = False,
    start_timeout: float = 0,
    verbose: bool = True,
    sleep: float | None = None,
    retry_key: str | None = None,
):
    """
    Wait for a VMS async task to start and complete.

    ``retry_key`` should be the CSI volume / PVC id when the caller is a
    Kubernetes RPC that may be retried by the external-attacher.
    """
    attempt = 1
    if retry_key:
        attempt = VTASK_RETRY_CACHE.bump(retry_key)
        if attempt > 1:
            logger.info(
                "VTask wait retry for volume %s (attempt %s); backing off initial poll",
                retry_key, attempt,
            )

    start_poll = vtask_poll_sleep(task_poll_key(task), sleep, attempt=attempt)
    task_line = 0

    def is_task_started(task):
        if isinstance(task, int):
            return session.vtasks(task)
        if isinstance(task, dict):
            if "async_task" in task:
                task = task["async_task"]
            return bunchify(task)
        if tasks := session.vtasks(name=task, log_result=False):
            if len(tasks) == 1:
                [task] = tasks
                return task
            if latest:
                return max(tasks, key=lambda t: t.id)
            raise Exception(f"Too many tasks with name '{task}': {[t.id for t in tasks]}")
        return False

    def is_task_complete(task_id):
        nonlocal task_line
        task = session.vtasks(task_id, log_result=False)
        if verbose:
            for line in task.messages[task_line:]:
                logger.info(line)
        task_line = len(task.messages)
        if task.state == "COMPLETED":
            return task
        if task.state == "FAILED":
            raise Exception(f"Task {task_id}: {task.messages[-1]}")
        if task.state != "RUNNING":
            raise TaskFailed(task=task, name=task.name, id=task.id, reason=task.messages[-1])
        raise TaskFailed(task=task, name=task.name, id=task.id, reason="timeout")

    if start_timeout:
        is_task_started = easypy_resilient.debug(
            acceptable=(
                MaxRetryError,
                ReadTimeoutError,
                TimeoutError,
                ConnectionResetError,
                ConnectionError,
                BrokenPipeError,
            ),
            msg="Failed to fetch VMS task",
            default=False,
        )(is_task_started)

    task = wait(
        start_timeout,
        lambda: is_task_started(task),
        sleep=start_poll,
        message=f"No such task found: {task}",
    )
    task_id = task.id
    complete_poll = vtask_poll_sleep(task_id, sleep, attempt=attempt)
    timeout = task.timeout_in_seconds + 10
    return wait(
        timeout,
        lambda: is_task_complete(task_id),
        sleep=complete_poll,
        message=False,
    )
