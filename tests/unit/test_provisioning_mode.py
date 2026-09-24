from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock

import grpc
import pytest

import vast_csi.csi_types as types
import vast_csi.plugins.base as plugin_base
import vast_csi.plugins.block as block_plugin
import vast_csi.plugins.nfs as nfs_plugin
from vast_csi.configuration import Config
from vast_csi.exceptions import Abort
from vast_csi.plugins.block import BlockNode
from vast_csi.plugins.nfs import CsiController, CsiNode


@pytest.mark.parametrize(
    "value, expected",
    [
        ("dynamic", "dynamic"),
        ("STATIC", "static"),
        (" static ", "static"),
    ],
)
def test_provisioning_mode(monkeypatch, value, expected):
    monkeypatch.setenv("X_CSI_PROVISIONING_MODE", value)

    conf = Config()

    assert conf.provisioning_mode == expected
    assert conf.static_provisioning is (expected == "static")


def test_invalid_provisioning_mode(monkeypatch):
    monkeypatch.setenv("X_CSI_PROVISIONING_MODE", "invalid")

    with pytest.raises(ValueError, match="invalid provisioning mode"):
        Config().provisioning_mode


def _rpc_types(response):
    return [capability.rpc.type for capability in response.capabilities]


def test_dynamic_controller_keeps_declared_capabilities(monkeypatch):
    monkeypatch.setattr(
        plugin_base, "CONF", SimpleNamespace(static_provisioning=False)
    )

    capabilities = _rpc_types(CsiController().ControllerGetCapabilities())

    assert capabilities == CsiController.CAPABILITIES


def test_static_controller_keeps_publish_and_snapshots(monkeypatch):
    monkeypatch.setattr(
        plugin_base, "CONF", SimpleNamespace(static_provisioning=True)
    )

    capabilities = _rpc_types(CsiController().ControllerGetCapabilities())

    assert capabilities == [
        types.CtrlCapabilityType.PUBLISH_UNPUBLISH_VOLUME,
        types.CtrlCapabilityType.CREATE_DELETE_SNAPSHOT,
    ]


def test_static_nfs_node_does_not_advertise_expansion(monkeypatch):
    monkeypatch.setattr(
        plugin_base, "CONF", SimpleNamespace(static_provisioning=True)
    )

    capabilities = _rpc_types(CsiNode().NodeGetCapabilities())

    assert capabilities == [types.NodeCapabilityType.GET_VOLUME_STATS]


def test_static_block_node_keeps_staging_and_stats(monkeypatch):
    monkeypatch.setattr(
        plugin_base, "CONF", SimpleNamespace(static_provisioning=True)
    )

    capabilities = _rpc_types(BlockNode().NodeGetCapabilities())

    assert capabilities == [
        types.NodeCapabilityType.STAGE_UNSTAGE_VOLUME,
        types.NodeCapabilityType.GET_VOLUME_STATS,
    ]


@pytest.mark.parametrize(
    "volume_context",
    [
        {"static_pv_create_views": "yes"},
        {"static_pv_create_quotas": "yes"},
    ],
)
def test_static_mode_does_not_create_vast_resources(
    monkeypatch, volume_capabilities, volume_context
):
    monkeypatch.setattr(
        nfs_plugin, "CONF", SimpleNamespace(static_provisioning=True)
    )
    capabilities = volume_capabilities(
        fs_type="ext4",
        mount_flags=[],
        mode=types.AccessModeType.SINGLE_NODE_WRITER,
    )

    with pytest.raises(Abort, match="cannot create VAST views or quotas"):
        CsiController().ControllerPublishVolume(
            None,
            "node-1",
            "/static/view",
            capabilities[0],
            volume_context,
        )


@pytest.mark.parametrize(
    "method",
    sorted(plugin_base.Instrumented.DYNAMIC_PROVISIONING_METHODS),
)
def test_instrumented_rejects_dynamic_rpcs_in_static_mode(monkeypatch, method):
    monkeypatch.setattr(
        plugin_base,
        "CONF",
        SimpleNamespace(static_provisioning=True, metrics_enabled=False),
    )

    def impl(self, request, context):
        return "should-not-run"

    impl.__name__ = method
    wrapped = plugin_base.Instrumented.logged(impl)

    context = MagicMock()
    context.peer.return_value = "peer"
    context.abort.side_effect = RuntimeError("aborted")

    with pytest.raises(RuntimeError, match="aborted"):
        wrapped(plugin_base.Instrumented(), MagicMock(), context)

    context.abort.assert_called_once_with(
        grpc.StatusCode.UNIMPLEMENTED,
        f"{method} is disabled when provisioningMode is static",
    )


def test_static_nfs_node_rejects_ephemeral_publish(monkeypatch):
    monkeypatch.setattr(
        nfs_plugin, "CONF", SimpleNamespace(static_provisioning=True)
    )

    with pytest.raises(Abort, match="Ephemeral volumes are disabled") as exc_info:
        CsiNode().NodePublishVolume(
            volume_id="vol-1",
            target_path="/tmp/static-ev",
            exit_stack=ExitStack(),
            mtls_manager=MagicMock(),
            volume_context={"csi.storage.k8s.io/ephemeral": "true"},
        )

    assert exc_info.value.code == grpc.StatusCode.FAILED_PRECONDITION


def test_static_block_node_rejects_ephemeral_publish(
    monkeypatch, volume_capabilities
):
    monkeypatch.setattr(
        block_plugin,
        "CONF",
        SimpleNamespace(
            static_provisioning=True,
            resolve_mount_symlinks=False,
        ),
    )
    capabilities = volume_capabilities(
        fs_type="ext4",
        mount_flags=[],
        mode=types.AccessModeType.SINGLE_NODE_WRITER,
    )

    with pytest.raises(Abort, match="Ephemeral volumes are disabled") as exc_info:
        BlockNode().NodePublishVolume(
            volume_id="vol-1",
            target_path="/tmp/static-ev-block",
            exit_stack=ExitStack(),
            luks_manager=MagicMock(),
            volume_capability=capabilities[0],
            volume_context={"csi.storage.k8s.io/ephemeral": "true"},
        )

    assert exc_info.value.code == grpc.StatusCode.FAILED_PRECONDITION
