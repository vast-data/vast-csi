from unittest.mock import Mock, patch

import pytest
from easypy.bunch import Bunch

from vast_csi.csi_types import ALREADY_EXISTS, INVALID_ARGUMENT, NOT_FOUND
from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.builders.cosi import cosi_clone_snap_name, cosi_clone_stream_name
from vast_csi.plugins.cosi import CosiProvisioner

CONF_MOCK = Mock(truncate_volume_name=None)


@pytest.fixture(autouse=True)
def _cosi_conf():
    with patch("vast_csi.plugins.cosi.CONF", CONF_MOCK):
        yield


@pytest.fixture
def cosi_provisioner():
    return CosiProvisioner()


SOURCE_BUCKET = "prod-dataset"
CLONE_BUCKET = "my-dev-clone"
SOURCE_PATH = "/data/prod-dataset"
TENANT_ID = 1

COMMON_PARAMS = dict(
    root_export="/clones",
    vip_pool_name="vippool-1",
    view_policy="s3_default_policy",
    scheme="http",
)


def _mock_session(*, source_view=None, dest_view=None, view_policy_tenant_id=TENANT_ID):
    session = Mock(name="vms_session")
    session.views.one.side_effect = lambda **kwargs: {
        SOURCE_BUCKET: source_view,
        CLONE_BUCKET: dest_view,
    }.get(kwargs.get("bucket"))
    session.viewpolicies.one.return_value = Bunch(
        id=1, tenant_id=view_policy_tenant_id, name="s3_default_policy"
    )
    session.users.ensure = Mock()
    session.snapshots.ensure = Mock(
        return_value=Bunch(id=99, name=f"cosi-snp-{CLONE_BUCKET}")
    )
    session.globalsnapstreams.ensure = Mock(
        return_value=Bunch(id=88, name=f"cosi-strm-{CLONE_BUCKET}")
    )
    session.views.ensure_s3view = Mock(
        return_value=dest_view or Bunch(
            tenant_id=TENANT_ID, id=7, path=f"/clones/{CLONE_BUCKET}"
        )
    )
    session.vippools.get_vip.return_value = "172.0.0.1"
    session.globalsnapstreams.ensure_snapshot_stream_deleted = Mock()
    session.snapshots.one.return_value = None
    session.snapshots.delete_by_id = Mock()
    session.folders.delete = Mock()
    session.views.delete_by_id = Mock()
    session.users.delete = Mock()
    return session


def _source_view(tenant_id=TENANT_ID):
    return Bunch(
        id=3,
        bucket=SOURCE_BUCKET,
        path=SOURCE_PATH,
        tenant_id=tenant_id,
    )


def _call_order_recorder(session):
    order = []

    def record(name):
        def wrapper(*args, **kwargs):
            order.append(name)
            if name == "snapshots.ensure":
                return Bunch(id=99, name=f"cosi-snp-{CLONE_BUCKET}")
            if name == "globalsnapstreams.ensure":
                return Bunch(id=88, name=f"cosi-strm-{CLONE_BUCKET}")
            if name == "views.ensure_s3view":
                return Bunch(
                    tenant_id=TENANT_ID, id=7, path=f"/clones/{CLONE_BUCKET}"
                )
            return None

        return wrapper

    session.snapshots.ensure.side_effect = record("snapshots.ensure")
    session.globalsnapstreams.ensure.side_effect = record("globalsnapstreams.ensure")
    session.views.ensure_s3view.side_effect = record("views.ensure_s3view")
    return order


class TestCosiCloneResourceNames:
    def test_stream_and_snap_names_fit_vms_limit(self):
        long_name = "vcsi325-clone-class" + ("x" * 40)
        assert len(cosi_clone_stream_name(long_name)) <= 64
        assert len(cosi_clone_snap_name(long_name)) <= 64

    def test_short_names_unchanged(self):
        assert cosi_clone_stream_name("my-bucket") == "cosi-strm-my-bucket"


class TestCosiBucketCloneCreate:
    def test_empty_bucket_no_snap_or_gss(self, cosi_provisioner):
        session = _mock_session()
        params = COMMON_PARAMS.copy()
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        session.users.ensure.assert_called_once()
        session.snapshots.ensure.assert_not_called()
        session.globalsnapstreams.ensure.assert_not_called()
        session.views.ensure_s3view.assert_called_once()
        assert "create_dir" not in session.views.ensure_s3view.call_args.kwargs

    def test_orphan_blocking_clones_rejected(self, cosi_provisioner):
        session = _mock_session()
        params = {**COMMON_PARAMS, "cosi.vastdata.com/blockingClones": "true"}
        with pytest.raises(Abort) as exc:
            cosi_provisioner.DriverCreateBucket(
                vms_session=session, name=CLONE_BUCKET, parameters=params
            )
        assert exc.value.code == INVALID_ARGUMENT
        session.views.ensure_s3view.assert_not_called()

    def test_source_bucket_alone_selects_clone(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        params = {**COMMON_PARAMS, "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET}
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        session.snapshots.ensure.assert_called_once()
        session.globalsnapstreams.ensure.assert_called_once()

    def test_clone_happy_path_order_and_ownership(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        order = _call_order_recorder(session)
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
        }
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        assert order == [
            "snapshots.ensure",
            "globalsnapstreams.ensure",
            "views.ensure_s3view",
        ]
        session.globalsnapstreams.ensure.assert_called_once_with(
            name=cosi_clone_stream_name(CLONE_BUCKET),
            snapshot_id=99,
            destination_path=f"/clones/{CLONE_BUCKET}",
            tenant_id=TENANT_ID,
            wait=False,
        )
        s3_kwargs = session.views.ensure_s3view.call_args.kwargs
        assert s3_kwargs["create_dir"] is False
        assert s3_kwargs["s3_object_ownership_rule"] == "BucketOwnerEnforced"
        assert "cosi.vastdata.com/blockingClones" not in s3_kwargs
        assert "cosi.vastdata.com/bucketOwnerEnforced" not in s3_kwargs

    def test_clone_driver_params_not_passed_to_s3view(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
            "cosi.vastdata.com/blockingClones": "true",
            "cosi.vastdata.com/bucketOwnerEnforced": "true",
        }
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        s3_kwargs = session.views.ensure_s3view.call_args.kwargs
        assert "cosi.vastdata.com/blockingClones" not in s3_kwargs
        assert "cosi.vastdata.com/bucketOwnerEnforced" not in s3_kwargs
        assert s3_kwargs["s3_object_ownership_rule"] == "BucketOwnerEnforced"

    def test_blocking_clones_waits_on_gss(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
            "cosi.vastdata.com/blockingClones": "true",
        }
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        assert session.globalsnapstreams.ensure.call_args.kwargs["wait"] is True
        s3_kwargs = session.views.ensure_s3view.call_args.kwargs
        assert "cosi.vastdata.com/blockingClones" not in s3_kwargs

    def test_bucket_owner_enforced_false(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
            "cosi.vastdata.com/bucketOwnerEnforced": "false",
        }
        cosi_provisioner.DriverCreateBucket(
            vms_session=session, name=CLONE_BUCKET, parameters=params
        )
        s3_kwargs = session.views.ensure_s3view.call_args.kwargs
        assert "s3_object_ownership_rule" not in s3_kwargs
        assert "cosi.vastdata.com/bucketOwnerEnforced" not in s3_kwargs


    def test_unknown_source_bucket(self, cosi_provisioner):
        session = _mock_session(source_view=None)
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": "missing-bucket",
        }
        with pytest.raises(Abort) as exc:
            cosi_provisioner.DriverCreateBucket(
                vms_session=session, name=CLONE_BUCKET, parameters=params
            )
        assert exc.value.code == NOT_FOUND
        session.users.delete.assert_not_called()

    def test_tenant_mismatch(self, cosi_provisioner):
        session = _mock_session(
            source_view=_source_view(tenant_id=2),
            view_policy_tenant_id=1,
        )
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
        }
        with pytest.raises(Abort) as exc:
            cosi_provisioner.DriverCreateBucket(
                vms_session=session, name=CLONE_BUCKET, parameters=params
            )
        assert exc.value.code == INVALID_ARGUMENT
        session.users.delete.assert_not_called()


    def test_clone_retry_after_view_create_failure(self, cosi_provisioner):
        """Snap + GSS created on first attempt; retry must succeed without new names."""
        session = _mock_session(source_view=_source_view())
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
        }
        session.views.ensure_s3view.side_effect = [
            RuntimeError("transient VMS error"),
            Bunch(tenant_id=TENANT_ID, id=7, path=f"/clones/{CLONE_BUCKET}"),
        ]

        with pytest.raises(RuntimeError, match="transient VMS error"):
            cosi_provisioner.DriverCreateBucket(
                vms_session=session,
                name=CLONE_BUCKET,
                parameters=params.copy(),
            )
        session.users.delete.assert_called_once_with(name=CLONE_BUCKET)

        resp = cosi_provisioner.DriverCreateBucket(
            vms_session=session,
            name=CLONE_BUCKET,
            parameters=params.copy(),
        )
        assert resp.bucket_id == f"{CLONE_BUCKET}@{TENANT_ID}@http://172.0.0.1:80"

        snap_name = cosi_clone_snap_name(CLONE_BUCKET)
        stream_name = cosi_clone_stream_name(CLONE_BUCKET)
        assert session.snapshots.ensure.call_count == 2
        assert session.globalsnapstreams.ensure.call_count == 2
        assert session.views.ensure_s3view.call_count == 2
        assert session.users.ensure.call_count == 2

        for call in session.snapshots.ensure.call_args_list:
            assert call.kwargs["name"] == snap_name
            assert call.kwargs["path"] == SOURCE_PATH
            assert call.kwargs["tenant_id"] == TENANT_ID

        for call in session.globalsnapstreams.ensure.call_args_list:
            assert call.kwargs["name"] == stream_name
            assert call.kwargs["snapshot_id"] == 99
            assert call.kwargs["destination_path"] == f"/clones/{CLONE_BUCKET}"
            assert call.kwargs["tenant_id"] == TENANT_ID

        for call in session.users.ensure.call_args_list:
            assert call.kwargs["name"] == CLONE_BUCKET

    def test_clone_failure_deletes_orphan_user(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        session.views.ensure_s3view.side_effect = RuntimeError("transient VMS error")
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
        }
        with pytest.raises(RuntimeError, match="transient VMS error"):
            cosi_provisioner.DriverCreateBucket(
                vms_session=session, name=CLONE_BUCKET, parameters=params
            )
        session.users.delete.assert_called_once_with(name=CLONE_BUCKET)

    def test_existing_view_wrong_path_fails(self, cosi_provisioner):
        session = _mock_session(source_view=_source_view())
        session.views.ensure_s3view.return_value = Bunch(
            tenant_id=TENANT_ID, id=7, path="/wrong/path"
        )
        params = {
            **COMMON_PARAMS,
            "cosi.vastdata.com/sourceBucket": SOURCE_BUCKET,
        }
        with pytest.raises(Abort) as exc:
            cosi_provisioner.DriverCreateBucket(
                vms_session=session, name=CLONE_BUCKET, parameters=params
            )
        assert exc.value.code == ALREADY_EXISTS
        # Abort must not delete bucket owner — existing view may already use it.
        session.users.delete.assert_not_called()


class TestCosiBucketCloneDelete:
    def test_delete_clone_bucket_cleans_gss_first(self, cosi_provisioner):
        session = _mock_session(
            source_view=_source_view(),
            dest_view=Bunch(id=7, path=f"/clones/{CLONE_BUCKET}", tenant_id=TENANT_ID),
        )
        order = []

        def record_gss(**kwargs):
            order.append("gss_delete")

        def record_folder(*args, **kwargs):
            order.append("folder_delete")

        session.globalsnapstreams.ensure_snapshot_stream_deleted.side_effect = record_gss
        session.folders.delete.side_effect = record_folder

        bucket_id = f"{CLONE_BUCKET}@{TENANT_ID}@http://172.0.0.1:80"
        cosi_provisioner.DriverDeleteBucket(
            vms_session=session,
            bucket_id=bucket_id,
            delete_context=None,
        )
        session.globalsnapstreams.ensure_snapshot_stream_deleted.assert_called_once_with(
            name=cosi_clone_stream_name(CLONE_BUCKET)
        )
        assert order.index("gss_delete") < order.index("folder_delete")

    def test_delete_clone_bucket_deletes_snapshot(self, cosi_provisioner):
        session = _mock_session(
            dest_view=Bunch(id=7, path=f"/clones/{CLONE_BUCKET}", tenant_id=TENANT_ID),
        )
        snap_name = cosi_clone_snap_name(CLONE_BUCKET)
        bucket_id = f"{CLONE_BUCKET}@{TENANT_ID}@http://172.0.0.1:80"
        cosi_provisioner.DriverDeleteBucket(
            vms_session=session,
            bucket_id=bucket_id,
            delete_context=None,
        )
        session.snapshots.delete.assert_called_once_with(name=snap_name)

    def test_delete_empty_bucket_gss_is_noop(self, cosi_provisioner):
        session = _mock_session(
            dest_view=Bunch(id=7, path=f"/buckets/{CLONE_BUCKET}", tenant_id=TENANT_ID),
        )
        bucket_id = f"{CLONE_BUCKET}@{TENANT_ID}@http://172.0.0.1:80"
        cosi_provisioner.DriverDeleteBucket(
            vms_session=session,
            bucket_id=bucket_id,
            delete_context=None,
        )
        session.globalsnapstreams.ensure_snapshot_stream_deleted.assert_called_once_with(
            name=cosi_clone_stream_name(CLONE_BUCKET)
        )
        session.folders.delete.assert_called_once()
        session.snapshots.delete.assert_called_once()
