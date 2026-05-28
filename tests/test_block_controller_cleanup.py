import contextlib
from contextlib import ExitStack
from unittest.mock import MagicMock

import pytest
from easypy.bunch import Bunch

from vast_csi.plugins.block import BlockController
import vast_csi.csi_types as types


@pytest.fixture()
def vms_session_mock():
    session = Bunch()
    session.volumes = Bunch()
    session.blockhostmappings = Bunch()
    session.blockhosts = Bunch()

    # Defaults; individual tests will override as needed
    session.volumes.one = MagicMock(return_value=Bunch(id=1, tenant_name="tenant-a"))
    session.blockhostmappings.ensure_unmap = MagicMock()
    session.blockhosts.one = MagicMock(return_value=Bunch(id=2, mapped_volumes_preview=[], nqn="nqn.2014-08.com.vastcsiblock:default:node-1"))
    session.blockhosts.delete_by_id = MagicMock()
    return session


@pytest.fixture()
def no_op_volume_lock(monkeypatch):
    calls = []

    @contextlib.contextmanager
    def _fake_volume_locked(key, **kwargs):
        calls.append(key)
        yield

    monkeypatch.setattr("vast_csi.plugins.block.resource_locked", _fake_volume_locked)
    return calls


@pytest.fixture()
def conf_with_prefix(monkeypatch):
    # Ensure block_nqn_prefix is set to CSI driver's prefix
    monkeypatch.setattr(
        "vast_csi.plugins.block.CONF",
        Bunch(block_nqn_prefix="nqn.2014-08.com.vastcsiblock", block_hosts_prefix="", block_hosts_auto_prune=True),
    )


def test_unpublish_deletes_host_when_last_volume(vms_session_mock, no_op_volume_lock, conf_with_prefix):
    controller = BlockController()
    node_id = "node-1"
    volume_id = "vol-1"

    resp = controller.ControllerUnpublishVolume(
        vms_session=vms_session_mock,
        node_id=node_id,
        volume_id=volume_id,
        exit_stack=ExitStack(),
    )

    assert isinstance(resp, types.CtrlUnpublishResp)
    vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once_with(
        volume__id=1, block_host__name=node_id
    )
    vms_session_mock.blockhosts.delete_by_id.assert_called_once_with(2)
    # lock taken with composite key
    assert no_op_volume_lock == [f"{node_id}:tenant-a"]


def test_unpublish_does_not_delete_host_when_mappings_exist(vms_session_mock, no_op_volume_lock):
    vms_session_mock.blockhosts.one = MagicMock(
        return_value=Bunch(id=2, mapped_volumes_preview=[{"id": 1}])
    )
    controller = BlockController()

    controller.ControllerUnpublishVolume(
        vms_session=vms_session_mock,
        node_id="node-1",
        volume_id="vol-1",
        exit_stack=ExitStack(),
    )

    vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once()
    vms_session_mock.blockhosts.delete_by_id.assert_not_called()


def test_unpublish_volume_not_found_skips_unmap_and_delete(vms_session_mock, no_op_volume_lock):
    vms_session_mock.volumes.one = MagicMock(return_value=None)
    controller = BlockController()

    controller.ControllerUnpublishVolume(
        vms_session=vms_session_mock,
        node_id="node-1",
        volume_id="missing-vol",
        exit_stack=ExitStack(),
    )

    vms_session_mock.blockhostmappings.ensure_unmap.assert_not_called()
    vms_session_mock.blockhosts.delete_by_id.assert_not_called()


def test_unpublish_host_not_found_no_delete(vms_session_mock, no_op_volume_lock):
    vms_session_mock.blockhosts.one = MagicMock(return_value=None)
    controller = BlockController()

    controller.ControllerUnpublishVolume(
        vms_session=vms_session_mock,
        node_id="node-1",
        volume_id="vol-1",
        exit_stack=ExitStack(),
    )

    vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once()
    vms_session_mock.blockhosts.delete_by_id.assert_not_called()


