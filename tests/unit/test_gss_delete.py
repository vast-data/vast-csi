"""Unit tests for GlobalSnapshotStream.ensure_snapshot_stream_deleted resilience."""

from unittest.mock import MagicMock

import pytest
from easypy.bunch import Bunch
from easypy.semver import SemVer

from vast_csi.csi_types import ABORTED
from vast_csi.exceptions import Abort
from vast_csi.session.resources import GlobalSnapshotStream


def _stream(stream_id=3, state="Active"):
    return Bunch(id=stream_id, status={"state": state})


@pytest.fixture
def gss():
    session = MagicMock()
    session.versions.get_sw_version.return_value = SemVer.loads_fuzzy("5.0.0")
    res = GlobalSnapshotStream(session)
    res.one = MagicMock()
    res.stop_snapshot_stream = MagicMock(return_value={"async_task": {"id": 82}})
    res.delete_by_id = MagicMock()
    return res, session


def test_missing_stream_is_noop(gss):
    res, session = gss
    res.one.return_value = None

    res.ensure_snapshot_stream_deleted(name="strm-x")

    res.stop_snapshot_stream.assert_not_called()
    session.wait_task.assert_not_called()
    res.delete_by_id.assert_not_called()


def test_finished_stream_deletes_without_stop(gss):
    res, session = gss
    res.one.return_value = _stream(state="Finished")

    res.ensure_snapshot_stream_deleted(name="strm-x")

    res.stop_snapshot_stream.assert_not_called()
    session.wait_task.assert_not_called()
    res.delete_by_id.assert_called_once_with(_id=3, data={"remove_dir": True})


def test_deleting_stream_aborts_for_retry(gss):
    """Stream already deleting: do not re-stop; Abort so caller retries."""
    res, session = gss
    res.one.return_value = _stream(state="DELETING")

    with pytest.raises(Abort) as exc_info:
        res.ensure_snapshot_stream_deleted(name="strm-x")

    assert exc_info.value.code == ABORTED
    res.stop_snapshot_stream.assert_not_called()
    session.wait_task.assert_not_called()
    res.delete_by_id.assert_not_called()


def test_stop_failure_stream_gone_is_success(gss):
    """Failed stop_gss but stream already gone → DeleteVolume can continue."""
    res, session = gss
    res.one.side_effect = [_stream(state="Active"), None]
    session.wait_task.side_effect = Exception(
        "Task 82: Task stop_gss (82) failed: INTERNAL_ERROR"
    )

    res.ensure_snapshot_stream_deleted(name="strm-x")

    res.stop_snapshot_stream.assert_called_once_with(3)
    session.wait_task.assert_called_once()
    res.delete_by_id.assert_not_called()


def test_stop_failure_stream_present_aborts_for_retry(gss):
    """Failed stop with stream still listed → Abort for idempotent retry."""
    res, session = gss
    res.one.return_value = _stream(state="Active")
    session.wait_task.side_effect = Exception(
        "Task 82: Task stop_gss (82) failed: INTERNAL_ERROR"
    )

    with pytest.raises(Abort) as exc_info:
        res.ensure_snapshot_stream_deleted(name="strm-x")

    assert exc_info.value.code == ABORTED
    res.stop_snapshot_stream.assert_called_once_with(3)
    res.delete_by_id.assert_not_called()


def test_stop_success_deletes_by_id(gss):
    res, session = gss
    res.one.return_value = _stream(state="Active")
    session.wait_task.return_value = Bunch(id=82, state="COMPLETED")

    res.ensure_snapshot_stream_deleted(name="strm-x")

    res.stop_snapshot_stream.assert_called_once_with(3)
    session.wait_task.assert_called_once()
    res.delete_by_id.assert_called_once_with(_id=3, data={"remove_dir": True})
