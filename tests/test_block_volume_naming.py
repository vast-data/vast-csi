from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock

import grpc
import pytest
from easypy.bunch import Bunch

from vast_csi.builders.block import (
    BlockVolumeFromSnapshotBuilder,
    BlockVolumeFromVolumeBuilder,
    EmptyBlockVolumeBuilder,
    _validate_volume_name_fmt,
)
from vast_csi.exceptions import Abort
from vast_csi.plugins.block import BlockController
from vast_csi import csi_types as types


CSI_ID = "pvc-abc123"
PVC_NAME = "my-pvc"
PVC_NAMESPACE = "default"


@pytest.fixture()
def block_builder_factory():
    """Factory fixture for building an EmptyBlockVolumeBuilder used to assert
    ``build_volume_name`` output across the (volume_group, volume_name_fmt)
    matrix.

    ``build_volume_name`` only reads dataclass attributes; vms_session,
    configuration and volume_capabilities are not touched and are mocked.
    """

    def __wrapped(volume_group="", volume_name_fmt="",
                  pvc_name=PVC_NAME, pvc_namespace=PVC_NAMESPACE):
        return EmptyBlockVolumeBuilder(
            vms_session=MagicMock(),
            configuration=MagicMock(),
            name=CSI_ID,
            volume_capabilities=MagicMock(),
            subsystem="subsys-1",
            volume_group=volume_group,
            volume_name_fmt=volume_name_fmt,
            pvc_name=pvc_name,
            pvc_namespace=pvc_namespace,
        )

    return __wrapped


# ---------------------------------------------------------------------------
# _validate_volume_name_fmt
# ---------------------------------------------------------------------------


def test_validate_empty_format_is_accepted():
    # Empty string keeps backward-compatible behavior (leaf falls back to
    # the CSI id) and therefore must not raise.
    _validate_volume_name_fmt("")


@pytest.mark.parametrize(
    "fmt",
    [
        "{id}",
        "csi-{id}",
        "csi-{namespace}-{name}-{id}",
        "{id}-{name}",
        "vol-{id}-{namespace}-trailing",
    ],
)
def test_validate_accepts_supported_placeholders(fmt):
    _validate_volume_name_fmt(fmt)


def test_validate_rejects_missing_id_placeholder():
    with pytest.raises(Abort) as exc:
        _validate_volume_name_fmt("csi-{namespace}-{name}")
    assert "{id}" in exc.value.message


def test_validate_rejects_unknown_placeholder():
    with pytest.raises(Abort) as exc:
        _validate_volume_name_fmt("csi-{cluster}-{id}")
    assert "cluster" in exc.value.message


def test_validate_rejects_malformed_template():
    with pytest.raises(Abort) as exc:
        _validate_volume_name_fmt("csi-{id")  # unterminated placeholder
    assert "Invalid volume_name_fmt" in exc.value.message


# ---------------------------------------------------------------------------
# BlockProvisionBase.build_volume_name
# ---------------------------------------------------------------------------


def test_build_volume_name_defaults_to_csi_id_when_both_empty(block_builder_factory):
    # No volume_group, no volume_name_fmt -> raw CSI id (today's behavior
    # for a storage class without volumeGroup).
    assert block_builder_factory().build_volume_name() == CSI_ID


def test_build_volume_name_uses_volume_group_only(block_builder_factory):
    # Only volume_group set -> historical behavior preserved: the CSI id
    # is appended as the leaf segment under the formatted path prefix.
    builder = block_builder_factory(volume_group="myteam/{namespace}/{name}")
    assert builder.build_volume_name() == f"myteam/{PVC_NAMESPACE}/{PVC_NAME}/{CSI_ID}"


def test_build_volume_name_uses_volume_name_fmt_only(block_builder_factory):
    builder = block_builder_factory(volume_name_fmt="csi-{namespace}-{name}-{id}")
    assert builder.build_volume_name() == f"csi-{PVC_NAMESPACE}-{PVC_NAME}-{CSI_ID}"


def test_build_volume_name_combines_group_and_fmt(block_builder_factory):
    builder = block_builder_factory(
        volume_group="myteam/{namespace}",
        volume_name_fmt="csi-{name}-{id}",
    )
    assert builder.build_volume_name() == f"myteam/{PVC_NAMESPACE}/csi-{PVC_NAME}-{CSI_ID}"


def test_build_volume_name_supports_id_not_at_end(block_builder_factory):
    # ``name__contains`` is used for lifecycle lookups (replacing the old
    # ``name__endswith``), so the {id} token is free to appear anywhere
    # in the leaf template.
    builder = block_builder_factory(volume_name_fmt="{id}-{name}")
    assert builder.build_volume_name() == f"{CSI_ID}-{PVC_NAME}"


def test_build_volume_name_falls_back_when_pvc_metadata_missing(block_builder_factory):
    # When the external-provisioner sidecar does not inject PVC metadata
    # (e.g. static provisioning), the format is ignored and the leaf
    # falls back to the CSI id. This mirrors the existing NFS behavior.
    builder = block_builder_factory(
        volume_name_fmt="csi-{namespace}-{name}-{id}",
        pvc_name=None,
        pvc_namespace=None,
    )
    assert builder.build_volume_name() == CSI_ID


def test_build_volume_name_strips_leading_slash_from_volume_group(block_builder_factory):
    # Mirrors the historical guarantee: the final name is a relative path
    # ("/" prefix is stripped by ``os.path.join("/", …).lstrip("/")``).
    builder = block_builder_factory(volume_group="/myteam")
    assert builder.build_volume_name() == f"myteam/{CSI_ID}"


# ---------------------------------------------------------------------------
# DeleteVolume collision-safe lookup
# ---------------------------------------------------------------------------


@pytest.fixture()
def delete_vms_session_mock():
    session = Bunch()
    session.volumes = Bunch()
    session.snapshots = Bunch()
    session.globalsnapstreams = Bunch()
    session.globalsnapstreams.ensure_snapshot_stream_deleted = MagicMock()
    session.snapshots.has_snapshots = MagicMock(return_value=False)
    session.volumes.one = MagicMock(return_value=Bunch(id=42))
    session.volumes.delete_by_id = MagicMock()
    return session


def test_delete_volume_uses_contains_and_deletes_by_id(delete_vms_session_mock):
    # The lookup must be by ``name__contains=<csi_id>`` (so that {id} placed
    # mid-template still resolves) and must delete by primary id.
    BlockController().DeleteVolume(
        vms_session=delete_vms_session_mock, volume_id=CSI_ID,
    )

    delete_vms_session_mock.volumes.one.assert_called_once_with(
        name__contains=CSI_ID,
    )
    delete_vms_session_mock.volumes.delete_by_id.assert_called_once_with(42)


def test_delete_volume_is_idempotent_when_volume_missing(delete_vms_session_mock):
    # CSI spec: DeleteVolume MUST be idempotent. Missing volume -> success,
    # no delete call.
    delete_vms_session_mock.volumes.one = MagicMock(return_value=None)

    BlockController().DeleteVolume(
        vms_session=delete_vms_session_mock, volume_id=CSI_ID,
    )

    delete_vms_session_mock.volumes.delete_by_id.assert_not_called()


def test_delete_volume_propagates_multiple_match_from_one(delete_vms_session_mock):
    # vast_csi.session.resources.Resource.one() raises when more than one
    # record matches. With ``name__contains`` we rely on this guard to
    # prevent accidental cascade-deletes from substring collisions.
    delete_vms_session_mock.volumes.one = MagicMock(
        side_effect=Exception("Too many 'volumes' found"),
    )

    with pytest.raises(Exception, match="Too many"):
        BlockController().DeleteVolume(
            vms_session=delete_vms_session_mock, volume_id=CSI_ID,
        )

    delete_vms_session_mock.volumes.delete_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# Lifecycle lookups switched from name__endswith to name__contains
# ---------------------------------------------------------------------------
# With ``volumeNameFormat``, the CSI id may appear anywhere in the VAST volume
# name (not necessarily at the end), so all lifecycle RPCs must resolve the
# volume by ``name__contains=<csi_id>``. These tests pin the lookup operator
# so future refactors cannot silently regress to ``name__endswith``.


def _path_volume_id(csi_id=CSI_ID):
    """Simulate a volume_id supplied by the sidecar as a full VAST path."""
    return f"/myteam/default/{csi_id}"


@pytest.fixture()
def expand_vms_session_mock():
    # ``volumes`` cannot be a Bunch because Bunch subclasses dict, so its
    # ``update`` method collides with the VMS API ``volumes.update(id, size=)``
    # that the controller calls. ``SimpleNamespace`` has no such collision.
    session = Bunch()
    session.volumes = SimpleNamespace(
        one=MagicMock(return_value=Bunch(id=7, size=10 * 1024 ** 3)),
        update=MagicMock(),
    )
    return session


def test_controller_expand_volume_uses_contains_lookup(expand_vms_session_mock):
    capacity_range = Bunch(required_bytes=20 * 1024 ** 3)

    BlockController().ControllerExpandVolume(
        vms_session=expand_vms_session_mock,
        volume_id=_path_volume_id(),
        capacity_range=capacity_range,
    )

    expand_vms_session_mock.volumes.one.assert_called_once_with(
        name__contains=CSI_ID,
    )
    # normalize_volume_id strips the path prefix before lookup.
    expand_vms_session_mock.volumes.update.assert_called_once_with(
        7, size=20 * 1024 ** 3,
    )


def test_controller_expand_volume_missing_volume_raises_not_found(
    expand_vms_session_mock,
):
    expand_vms_session_mock.volumes.one = MagicMock(return_value=None)

    with pytest.raises(Abort) as exc:
        BlockController().ControllerExpandVolume(
            vms_session=expand_vms_session_mock,
            volume_id=CSI_ID,
            capacity_range=Bunch(required_bytes=1),
        )

    assert exc.value.code == grpc.StatusCode.NOT_FOUND


@pytest.fixture()
def unpublish_vms_session_mock():
    session = Bunch()
    session.volumes = Bunch()
    session.volumes.one = MagicMock(return_value=None)
    session.blockhostmappings = Bunch(ensure_unmap=MagicMock())
    session.blockhosts = Bunch(one=MagicMock(return_value=None))
    return session


def test_controller_unpublish_uses_contains_lookup(unpublish_vms_session_mock):
    with ExitStack() as stack:
        BlockController().ControllerUnpublishVolume(
            vms_session=unpublish_vms_session_mock,
            node_id="node-1",
            volume_id=_path_volume_id(),
            exit_stack=stack,
        )

    unpublish_vms_session_mock.volumes.one.assert_called_once_with(
        name__contains=CSI_ID,
    )
    # CSI spec: ControllerUnpublishVolume MUST be idempotent. Missing volume
    # short-circuits before touching block host mappings.
    unpublish_vms_session_mock.blockhostmappings.ensure_unmap.assert_not_called()


@pytest.fixture()
def create_snapshot_vms_session_mock():
    session = Bunch()
    session.volumes = Bunch()
    session.volumes.one = MagicMock(
        return_value=Bunch(
            id=11,
            name=f"myteam/{CSI_ID}",
            view_id=99,
        ),
    )
    session.views = Bunch(
        get_subsystem_by_id=MagicMock(
            return_value=Bunch(path="/subsystems/sub1", tenant_id=1, name="sub1"),
        ),
    )
    session.snapshots = Bunch(
        ensure=MagicMock(return_value=Bunch(id=22, created="2025-01-01T00:00:00Z")),
    )
    return session


def test_create_snapshot_uses_contains_lookup(create_snapshot_vms_session_mock):
    parameters = {
        "csi.storage.k8s.io/volumesnapshot/name": "snap-1",
        "csi.storage.k8s.io/volumesnapshot/namespace": "default",
        "snapshot_name_fmt": "snap-{namespace}-{name}-{id}",
    }

    BlockController().CreateSnapshot(
        vms_session=create_snapshot_vms_session_mock,
        source_volume_id=_path_volume_id(),
        name="snap-csi-id",
        parameters=parameters,
    )

    create_snapshot_vms_session_mock.volumes.one.assert_called_once_with(
        name__contains=CSI_ID,
    )


def test_create_snapshot_missing_source_volume_raises_not_found(
    create_snapshot_vms_session_mock,
):
    create_snapshot_vms_session_mock.volumes.one = MagicMock(return_value=None)

    with pytest.raises(Abort) as exc:
        BlockController().CreateSnapshot(
            vms_session=create_snapshot_vms_session_mock,
            source_volume_id=CSI_ID,
            name="snap-csi-id",
            parameters={
                "csi.storage.k8s.io/volumesnapshot/name": "snap-1",
                "csi.storage.k8s.io/volumesnapshot/namespace": "default",
            },
        )

    assert exc.value.code == grpc.StatusCode.NOT_FOUND


# ---------------------------------------------------------------------------
# Clone builders: source uses name__contains; destination uses exact name=
# ---------------------------------------------------------------------------
# The destination volume_name is the canonical VAST name built by
# ``build_volume_name`` and therefore must match exactly — otherwise a
# substring collision with an unrelated volume could short-circuit the clone
# and return the wrong volume to the caller.


SRC_CSI_ID = "pvc-src-999"


def _make_clone_vms_session():
    """Build a ``vms_session`` whose nested namespaces are real attribute
    holders. ``MagicMock`` auto-creates child mocks on attribute access, so
    assigning ``session.volumes.one = MagicMock(...)`` from a test does not
    actually replace what the production code sees — using
    ``SimpleNamespace`` makes the substitution explicit and observable.
    """
    return SimpleNamespace(
        volumes=SimpleNamespace(one=MagicMock(), update=MagicMock()),
        views=SimpleNamespace(
            get_subsystem=MagicMock(),
            get_subsystem_by_id=MagicMock(),
        ),
        snapshots=SimpleNamespace(get=MagicMock(), ensure=MagicMock()),
        globalsnapstreams=SimpleNamespace(wait_by_loanee_path=MagicMock()),
    )


def _clone_builder_kwargs(volume_content_source):
    # ``volume_capabilities`` must expose only the attributes touched by
    # ``volume_context`` / ``build_volume`` with real values — otherwise a
    # ``MagicMock`` auto-attribute becomes a truthy non-string and breaks
    # the proto ``map<str,str>`` serialization of ``volume_context``.
    return dict(
        vms_session=_make_clone_vms_session(),
        configuration=SimpleNamespace(truncate_volume_name=None),
        name=CSI_ID,
        volume_capabilities=SimpleNamespace(
            mount_flags_str="", is_filesystem=False,
        ),
        subsystem="sub1",
        transport_type="TCP",
        tenant_name="tenant-a",
        pvc_name=PVC_NAME,
        pvc_namespace=PVC_NAMESPACE,
        blocking_clones=False,
        volume_content_source=volume_content_source,
    )


def test_clone_from_volume_uses_contains_for_source_and_exact_for_destination():
    vcs = types.VolumeContentSource(
        volume=types.VolumeSource(volume_id=SRC_CSI_ID),
    )
    builder = BlockVolumeFromVolumeBuilder(**_clone_builder_kwargs(vcs))

    src_volume = Bunch(id=1, name=f"team/{SRC_CSI_ID}", view_id=10)
    src_view = Bunch(
        id=10, path="/subsystems/sub1", tenant_id=1,
        tenant_name="tenant-a", name="sub1", nqn="nqn.sub1",
    )
    dst_volume = Bunch(id=2, name=CSI_ID, nguid="nguid-2", size=100)

    # First .one() resolves the source by substring; second resolves the
    # destination by exact name. Order matters for the side_effect list.
    builder.vms_session.volumes.one = MagicMock(side_effect=[src_volume, dst_volume])
    builder.vms_session.views.get_subsystem_by_id = MagicMock(return_value=src_view)

    builder.build_volume()

    calls = builder.vms_session.volumes.one.call_args_list
    assert calls[0].kwargs == {"name__contains": SRC_CSI_ID}
    assert calls[1].kwargs == {"name": CSI_ID}


def test_clone_from_snapshot_uses_exact_match_for_destination():
    vcs = types.VolumeContentSource(
        snapshot=types.SnapshotSource(snapshot_id="snap-src-1"),
    )
    builder = BlockVolumeFromSnapshotBuilder(**_clone_builder_kwargs(vcs))

    # ``snapshot.tenant_name`` is propagated to the resulting volume_context;
    # it is required by ``BlockVolumeFromSnapshotBuilder.build_volume``.
    snapshot = Bunch(id=33, tenant_name="tenant-a")
    dst_view = Bunch(
        id=10, path="/subsystems/sub1", tenant_id=1,
        tenant_name="tenant-a", name="sub1", nqn="nqn.sub1",
    )
    dst_volume = Bunch(id=2, name=CSI_ID, nguid="nguid-2", size=100)

    builder.vms_session.snapshots.get = MagicMock(return_value=snapshot)
    builder.vms_session.views.get_subsystem = MagicMock(return_value=dst_view)
    builder.vms_session.volumes.one = MagicMock(return_value=dst_volume)

    builder.build_volume()

    builder.vms_session.volumes.one.assert_called_once_with(name=CSI_ID)
