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




NQN_PREFIX = "nqn.2014-08.com.vastcsiblock:"
NQN_TENANT = "mytenant"
NQN_HOST = "worker-node-1"
NQN_SEED = "test-seed"


@pytest.fixture()
def publish_conf(monkeypatch):
    monkeypatch.setattr(
        "vast_csi.plugins.block.CONF",
        Bunch(
            block_nqn_prefix=NQN_PREFIX,
            block_hosts_prefix="",
            block_hosts_auto_prune=False,
            use_local_ip_for_mount="127.0.0.1",
        ),
    )


@pytest.fixture()
def publish_session():
    session = Bunch()
    session.blockhosts = Bunch()
    session.blockhostmappings = Bunch()
    session.vippools = Bunch()
    session.blockhosts.ensure = MagicMock(
        return_value=Bunch(id=2, nqn=f"{NQN_PREFIX}{NQN_TENANT}:{NQN_HOST}")
    )
    session.blockhostmappings.ensure_map_exclusive = MagicMock()
    session.vippools.get_vip = MagicMock(return_value="10.0.0.1")
    return session


def _publish_volume_context(**extra):
    ctx = dict(
        volume_id="1",
        tenant_name=NQN_TENANT,
        subsystem="mysub",
        transport_type="TCP",
        subsystem_nqn="nqn.subsystem",
        nguid="nguid-1",
        vip_pool_name="vippool-1",
    )
    ctx.update(extra)
    return ctx


def test_publish_passes_legacy_nqn_to_ensure(
    publish_session, publish_conf, volume_capabilities
):
    caps = volume_capabilities(
        mode=types.AccessModeType.SINGLE_NODE_WRITER, access_type="block"
    )
    BlockController().ControllerPublishVolume(
        vms_session=publish_session,
        node_id=NQN_HOST,
        volume_id="vol-1",
        volume_capability=caps[0],
        exit_stack=ExitStack(),
        volume_context=_publish_volume_context(),
    )
    assert publish_session.blockhosts.ensure.call_args.kwargs["nqn"] == (
        f"{NQN_PREFIX}{NQN_TENANT}:{NQN_HOST}"
    )


def test_publish_passes_obfuscated_nqn_when_seed_present(
    publish_session, publish_conf, volume_capabilities
):
    from vast_csi.block_utils import compute_block_host_nqn

    expected = compute_block_host_nqn(
        prefix=NQN_PREFIX, tenant_name=NQN_TENANT, block_host_name=NQN_HOST, seed=NQN_SEED
    )
    publish_session.blockhosts.ensure = MagicMock(
        return_value=Bunch(id=2, nqn=expected)
    )
    caps = volume_capabilities(
        mode=types.AccessModeType.SINGLE_NODE_WRITER, access_type="block"
    )
    resp = BlockController().ControllerPublishVolume(
        vms_session=publish_session,
        node_id=NQN_HOST,
        volume_id="vol-1",
        volume_capability=caps[0],
        exit_stack=ExitStack(),
        volume_context=_publish_volume_context(host_nqn_obfuscation="true"),
        secrets={"host_nqn_seed": NQN_SEED},
    )
    assert publish_session.blockhosts.ensure.call_args.kwargs["nqn"] == expected
    assert resp.publish_context["host_nqn"] == expected


def test_publish_rejects_obfuscation_without_seed(
    publish_session, publish_conf, volume_capabilities
):
    from vast_csi.exceptions import Abort

    caps = volume_capabilities(
        mode=types.AccessModeType.SINGLE_NODE_WRITER, access_type="block"
    )
    with pytest.raises(Abort) as exc:
        BlockController().ControllerPublishVolume(
            vms_session=publish_session,
            node_id=NQN_HOST,
            volume_id="vol-1",
            volume_capability=caps[0],
            exit_stack=ExitStack(),
            volume_context=_publish_volume_context(host_nqn_obfuscation="true"),
            secrets={},
        )
    assert "host_nqn_seed is missing" in exc.value.message
    publish_session.blockhosts.ensure.assert_not_called()
