"""
Controller create/publish/unpublish/delete through the real gRPC wrapper, with no cluster.

The VMS session and the grpc context are hand-rolled stand-ins. Nothing here records
calls: a recording mock keeps every invocation and looks like a leak by itself. Each
iteration uses a new volume name, the way the Orion create/delete wave does.

Run with:
    pytest -m memleak tests/unit/test_controller_lifecycle_memory.py -v -s
"""

import logging
import uuid

import pytest
from easypy.bunch import Bunch

import vast_csi.metrics as metrics
import vast_csi.plugins.base as plugin_base
from vast_csi.plugins.base import Instrumented
from vast_csi.plugins.nfs import CsiController
from vast_csi.proto import csi_pb2
from test_library_memory_leaks import assert_steady_state

pytestmark = pytest.mark.memleak

# One batch is one Orion-style wave. The check fails only when the last three
# batches all grow, so a cache filling once during warmup is not a failure.
_VOLUMES_PER_BATCH = 40

_VIEW = Bunch(path="/k8s/x", id=1, tenant_id=1, tenant_name="default", protocols=["NFS4"])
_QUOTA = Bunch(id=1, hard_limit=1 << 30, tenant_id=1, path="/k8s/x", tenant_name="default")
_POLICY = Bunch(
    name="default", id=1, tenant_id=1,
    nfs_enforce_tls=False, nfs_enforce_tls_relaxed=False, nfs_enforce_mtls=False,
)

_CAPABILITY = csi_pb2.VolumeCapability(
    mount=csi_pb2.VolumeCapability.MountVolume(fs_type="", mount_flags=["vers=4.1"]),
    access_mode=csi_pb2.VolumeCapability.AccessMode(
        mode=csi_pb2.VolumeCapability.AccessMode.MULTI_NODE_MULTI_WRITER
    ),
)
_SECRETS = {"username": "admin", "password": "pw", "endpoint": "10.0.0.1"}
_PARAMETERS = {"root_export": "/k8s", "view_policy": "default", "vip_pool_name": "vippool-1"}


def _none(*_args, **_kwargs):
    return None


class _FakeResource:
    def __init__(self, session):
        self.session = session


class _FakeViews(_FakeResource):
    ensure = staticmethod(lambda **_kw: _VIEW)
    ensure_cached = ensure
    one = staticmethod(lambda **_kw: _VIEW)
    one_cached = one
    delete = staticmethod(_none)
    update = staticmethod(_none)


class _FakeQuotas(_FakeResource):
    ensure = staticmethod(lambda **_kw: _QUOTA)
    ensure_cached = ensure
    one = staticmethod(lambda **_kw: _QUOTA)
    one_cached = one
    delete = staticmethod(_none)
    delete_by_id = staticmethod(_none)
    update = staticmethod(_none)


class _FakeVipPools(_FakeResource):
    get_vip = staticmethod(lambda *_a, **_k: "127.0.0.1")


class _FakeViewPolicies(_FakeResource):
    one = staticmethod(lambda **_kw: _POLICY)
    one_cached = one


class _FakeGlobalSnapStreams(_FakeResource):
    ensure_snapshot_stream_deleted = staticmethod(_none)


class _FakeSnapshots(_FakeResource):
    has_snapshots = staticmethod(lambda *_a, **_k: [])
    list = staticmethod(lambda *_a, **_k: [])


class _FakeFolders(_FakeResource):
    delete = staticmethod(_none)


class _FakeSession:
    """Stands in for VmsSession. Identity is fixed, the way a real session hashes credentials."""

    def __init__(self, config):
        self.config = config
        self.views = _FakeViews(self)
        self.quotas = _FakeQuotas(self)
        self.vippools = _FakeVipPools(self)
        self.viewpolicies = _FakeViewPolicies(self)
        self.globalsnapstreams = _FakeGlobalSnapStreams(self)
        self.snapshots = _FakeSnapshots(self)
        self.folders = _FakeFolders(self)

    def __hash__(self):
        return 1234567

    def __eq__(self, other):
        return isinstance(other, _FakeSession)

    def __str__(self):
        return "FakeSession[10.0.0.1]"

    __repr__ = __str__

    delete_folder = staticmethod(_none)


class _FakeContext:
    """Enough of grpc.ServicerContext for the Instrumented wrapper."""

    def peer(self):
        return "ipv4:127.0.0.1:1234"

    def abort(self, code, details):
        raise RuntimeError(f"ABORT {code}: {details}")

    def is_active(self):
        return True


def _bind_rpcs():
    """Re-apply the gRPC wrapper. The unit conftest strips it so other tests call raw methods."""
    controller = CsiController()
    rpcs = {
        name: Instrumented.logged(getattr(CsiController, name))
        for name in (
            "CreateVolume",
            "ControllerPublishVolume",
            "ControllerUnpublishVolume",
            "DeleteVolume",
        )
    }
    return controller, rpcs


def _one_volume(controller, rpcs, ctx):
    name = f"pvc-{uuid.uuid4()}"
    rpcs["CreateVolume"](
        controller,
        csi_pb2.CreateVolumeRequest(
            name=name,
            capacity_range=csi_pb2.CapacityRange(required_bytes=1 << 30),
            volume_capabilities=[_CAPABILITY],
            parameters=_PARAMETERS,
            secrets=_SECRETS,
        ),
        ctx,
    )
    rpcs["ControllerPublishVolume"](
        controller,
        csi_pb2.ControllerPublishVolumeRequest(
            volume_id=name,
            node_id="memleak-node",
            volume_capability=_CAPABILITY,
            volume_context=dict(_PARAMETERS),
            secrets=_SECRETS,
        ),
        ctx,
    )
    rpcs["ControllerUnpublishVolume"](
        controller,
        csi_pb2.ControllerUnpublishVolumeRequest(
            volume_id=name, node_id="memleak-node", secrets=_SECRETS
        ),
        ctx,
    )
    rpcs["DeleteVolume"](
        controller,
        csi_pb2.DeleteVolumeRequest(volume_id=name, secrets=_SECRETS),
        ctx,
    )


def test_controller_lifecycle_reaches_steady_state(monkeypatch):
    """Unique volumes through the real wrapper must not keep the heap growing."""
    import vast_csi.plugins.nfs as plugin_nfs

    session = _FakeSession(plugin_nfs.CONF)
    monkeypatch.setattr(plugin_base, "CONF", plugin_nfs.CONF)
    monkeypatch.setattr(plugin_base, "instantiate_session_from_secret", lambda *_a, **_k: session)
    monkeypatch.setenv("X_CSI_METRICS_ENABLED", "true")
    if metrics.METRIC_FACTORY is None:
        metrics.METRIC_FACTORY = metrics.MetricFactory(is_node_service=False)

    controller, rpcs = _bind_rpcs()
    ctx = _FakeContext()
    # Fail here, with the RPC error, if the fake no longer covers the path.
    _one_volume(controller, rpcs, ctx)

    disabled = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        def batch():
            for _ in range(_VOLUMES_PER_BATCH):
                _one_volume(controller, rpcs, ctx)

        assert_steady_state(
            batch,
            label=f"controller lifecycle x{_VOLUMES_PER_BATCH}",
            warmup=1,
            rounds=5,
            py_tolerance=4 * 1024,
            native_tolerance=64 * 1024,
        )
    finally:
        logging.disable(disabled)
