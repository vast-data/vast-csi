"""Tests for vast_csi.session.wait (VTask polling, backoff, retry cache)."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from easypy.bunch import bunchify
from easypy.sync import TimeoutException

from vast_csi.exceptions import TaskFailed
from vast_csi.session import wait as wait_mod
from vast_csi.session.wait import (
    POLL_INTERVAL_MAX,
    POLL_INTERVAL_MIN,
    RETRY_EXTRA_MIN,
    VtaskRetryCache,
    task_poll_key,
    vtask_poll_sleep,
    wait_task,
)


@pytest.fixture(autouse=True)
def isolated_retry_cache():
    original = wait_mod.VTASK_RETRY_CACHE
    wait_mod.VTASK_RETRY_CACHE = VtaskRetryCache(ttl_seconds=60)
    yield
    wait_mod.VTASK_RETRY_CACHE = original


def _task(
    *,
    id=1,
    state="COMPLETED",
    timeout_in_seconds=30,
    messages=None,
    name="bulk_map",
):
    return bunchify(
        dict(
            id=id,
            state=state,
            timeout_in_seconds=timeout_in_seconds,
            messages=messages if messages is not None else [f"line-{state}"],
            name=name,
        )
    )


def _run_wait_until_done(timeout, pred, sleep=0.5, **kwargs):
    """Minimal easypy.wait stand-in for unit tests (no real sleeping)."""
    for is_final in (False, True):
        try:
            try:
                ret = pred(is_final_attempt=is_final)
            except TypeError:
                ret = pred()
        except TaskFailed as exc:
            if getattr(exc, "reason", None) == "timeout":
                continue
            raise
        if ret not in (None, False):
            return ret
    raise TimeoutException("predicate not satisfied", duration=timeout)


# --- task_poll_key ---


class TestTaskPollKey:
    def test_int_task_id(self):
        assert task_poll_key(42) == 42

    def test_async_task_dict_prefers_id(self):
        assert task_poll_key({"async_task": {"id": 7, "name": "map"}}) == 7

    def test_async_task_dict_falls_back_to_name(self):
        assert task_poll_key({"async_task": {"name": "unmap"}}) == "unmap"

    def test_flat_dict_without_async_task_wrapper(self):
        assert task_poll_key({"id": 9, "name": "x"}) == 9

    def test_string_task_name(self):
        assert task_poll_key("replicate") == "replicate"


# --- vtask_poll_sleep ---


class TestVtaskPollSleep:
    def test_default_exponential_range_with_jitter(self):
        first, max_iv = vtask_poll_sleep(12345)
        assert POLL_INTERVAL_MIN <= first < max_iv
        assert max_iv == POLL_INTERVAL_MAX

    def test_jitter_stable_for_same_task_key(self):
        assert vtask_poll_sleep(99) == vtask_poll_sleep(99)

    def test_jitter_differs_across_keys(self):
        a, _ = vtask_poll_sleep("pvc-a")
        b, _ = vtask_poll_sleep("pvc-b")
        assert a != b or hash("pvc-a") % 1000 == hash("pvc-b") % 1000

    def test_none_task_key_no_jitter_offset(self):
        first, max_iv = vtask_poll_sleep(None)
        assert first == POLL_INTERVAL_MIN
        assert max_iv == POLL_INTERVAL_MAX

    def test_retry_attempt_adds_extra_to_minimum(self):
        first, _ = vtask_poll_sleep(1, attempt=1)
        third, _ = vtask_poll_sleep(1, attempt=3)
        assert third >= first + 2 * RETRY_EXTRA_MIN

    def test_sleep_override_becomes_minimum(self):
        first, max_iv = vtask_poll_sleep(1, sleep=5)
        assert first >= 5
        assert max_iv == POLL_INTERVAL_MAX

    def test_large_sleep_returns_fixed_interval(self):
        assert vtask_poll_sleep(1, sleep=20) == 20

    def test_attempt_one_has_no_retry_extra(self):
        base, _ = vtask_poll_sleep(1, attempt=1)
        assert base < POLL_INTERVAL_MIN + RETRY_EXTRA_MIN


# --- VtaskRetryCache ---


class TestVtaskRetryCache:
    def test_counts_attempts_per_pvc(self):
        cache = VtaskRetryCache(ttl_seconds=60)
        assert cache.bump("pvc-abc") == 1
        assert cache.bump("pvc-abc") == 2
        assert cache.bump("pvc-other") == 1

    def test_prunes_stale_entries(self):
        cache = VtaskRetryCache(ttl_seconds=0.05)
        assert cache.bump("pvc-stale") == 1
        time.sleep(0.1)
        assert cache.bump("pvc-stale") == 1

    def test_concurrent_bumps_are_thread_safe(self):
        cache = VtaskRetryCache(ttl_seconds=60)
        pvc = "pvc-parallel"
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            cache.bump(pvc)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert cache.bump(pvc) == 9


# --- wait_task (mocked session + wait) ---


class TestWaitTask:
    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_wait_by_int_task_id_until_completed(self, _mock_wait):
        session = MagicMock()
        running = _task(id=5, state="RUNNING")
        completed = _task(id=5, state="COMPLETED")
        session.vtasks.side_effect = [
            running,  # is_task_started(5)
            running,  # is_task_complete first poll
            completed,
        ]

        result = wait_task(session, 5)

        assert result.state == "COMPLETED"
        assert session.vtasks.call_args_list[0] == ((5,),)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_wait_by_dict_async_task_handle(self, _mock_wait):
        session = MagicMock()
        task = _task(id=11, state="COMPLETED")
        session.vtasks.return_value = task

        payload = {"async_task": {"id": 11, "name": "bulk", "timeout_in_seconds": 30}}
        result = wait_task(session, payload)

        assert result.id == 11
        session.vtasks.assert_called_once_with(11, log_result=False)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_wait_by_name_single_match(self, _mock_wait):
        session = MagicMock()
        task = _task(id=3, state="COMPLETED", name="map_vol")
        session.vtasks.side_effect = [
            [task],  # lookup by name
            task,
            task,
        ]

        result = wait_task(session, "map_vol")

        assert result.name == "map_vol"
        session.vtasks.assert_any_call(name="map_vol", log_result=False)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_wait_by_name_latest_picks_highest_id(self, _mock_wait):
        session = MagicMock()
        older = _task(id=1, state="COMPLETED", name="dup")
        newer = _task(id=99, state="COMPLETED", name="dup")
        session.vtasks.side_effect = [
            [older, newer],
            newer,
            newer,
        ]

        result = wait_task(session, "dup", latest=True)

        assert result.id == 99

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_wait_by_name_multiple_without_latest_raises(self, _mock_wait):
        session = MagicMock()
        session.vtasks.return_value = [_task(id=1), _task(id=2)]

        with pytest.raises(Exception, match="Too many tasks"):
            wait_task(session, "ambiguous")

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_failed_task_raises_plain_exception(self, _mock_wait):
        session = MagicMock()
        failed = _task(id=4, state="FAILED", messages=["boom"])
        session.vtasks.side_effect = [failed, failed]

        with pytest.raises(Exception, match="Task 4: boom"):
            wait_task(session, 4)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_non_running_non_completed_raises_task_failed(self, _mock_wait):
        session = MagicMock()
        pending = _task(id=6, state="PENDING", messages=["still pending"])
        session.vtasks.side_effect = [pending, pending]

        with pytest.raises(TaskFailed):
            wait_task(session, 6)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_running_polls_until_completed(self, _mock_wait):
        session = MagicMock()
        running = _task(id=7, state="RUNNING")
        done = _task(id=7, state="COMPLETED")
        session.vtasks.side_effect = [running, running, done]

        result = wait_task(session, 7)

        assert result.state == "COMPLETED"
        assert session.vtasks.call_count == 3

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_passes_exponential_sleep_to_wait(self, _mock_wait):
        session = MagicMock()
        task = _task(id=8, state="COMPLETED")
        session.vtasks.return_value = task
        captured = []

        def recording_wait(timeout, pred=None, sleep=0.5, **kwargs):
            captured.append(sleep)
            return _run_wait_until_done(timeout, pred, sleep=sleep, **kwargs)

        with patch.object(wait_mod, "wait", side_effect=recording_wait):
            wait_task(session, 8)

        assert len(captured) == 2
        assert captured[0] == vtask_poll_sleep(8, attempt=1)
        assert captured[1] == vtask_poll_sleep(8, attempt=1)

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_retry_key_increases_attempt_and_poll_minimum(self, _mock_wait):
        session = MagicMock()
        task = _task(id=9, state="COMPLETED")
        session.vtasks.return_value = task
        pvc = "pvc-retry-me"

        wait_mod.VTASK_RETRY_CACHE.bump(pvc)  # simulate prior K8s attempt

        captured = []

        def recording_wait(timeout, pred=None, sleep=0.5, **kwargs):
            captured.append(sleep)
            return _run_wait_until_done(timeout, pred, sleep=sleep, **kwargs)

        with patch.object(wait_mod, "wait", side_effect=recording_wait):
            wait_task(session, 9, retry_key=pvc)

        assert wait_mod.VTASK_RETRY_CACHE.bump(pvc) == 3
        assert captured[0] == vtask_poll_sleep(9, attempt=2)
        assert captured[0][0] > vtask_poll_sleep(9, attempt=1)[0]

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_sleep_override_applied_to_both_phases(self, _mock_wait):
        session = MagicMock()
        task = _task(id=10, state="COMPLETED")
        session.vtasks.return_value = task
        captured = []

        def recording_wait(timeout, pred=None, sleep=0.5, **kwargs):
            captured.append(sleep)
            return _run_wait_until_done(timeout, pred, sleep=sleep, **kwargs)

        with patch.object(wait_mod, "wait", side_effect=recording_wait):
            wait_task(session, 10, sleep=20)

        assert captured == [20, 20]

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_verbose_false_skips_message_logging(self, _mock_wait, caplog):
        session = MagicMock()
        task = _task(id=12, state="COMPLETED", messages=["log-me"])
        session.vtasks.return_value = task

        with caplog.at_level("INFO"):
            wait_task(session, 12, verbose=False)

        assert "log-me" not in caplog.text

    @patch.object(wait_mod, "wait", side_effect=_run_wait_until_done)
    def test_completion_timeout_includes_grace_period(self, _mock_wait):
        session = MagicMock()
        started = _task(id=13, state="RUNNING", timeout_in_seconds=100)
        completed = _task(id=13, state="COMPLETED", timeout_in_seconds=100)
        session.vtasks.side_effect = [started, started, completed]
        timeouts = []

        def recording_wait(timeout, pred=None, sleep=0.5, **kwargs):
            timeouts.append(timeout)
            return _run_wait_until_done(timeout, pred, sleep=sleep, **kwargs)

        with patch.object(wait_mod, "wait", side_effect=recording_wait):
            wait_task(session, 13)

        assert timeouts[1] == 110
