import json
import pytest
import grpc
from easypy.bunch import Bunch
from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.plugins.cosi import CosiProvisioner, parse_lifecycle_rules


COMMON_PARAMS = dict(
    root_export="/buckets",
    vip_pool_name="vippool-1",
    view_policy="default",
    qos_policy="default",
    protocols="nfs, nfs4, smb",
    scheme="http",
    s3_locks_retention_mode="COMPILANCE",
    s3_versioning="true",
    s3_locks="true",
    locking="true",
    s3_locks_retention_period="1d",
    default_retention_period="1d",
    allow_s3_anonymous_access="true",
)


class TestParseLifecycleRules:
    def test_parse_multi_rule_and_default_names(self):
        raw = json.dumps([
            {"expiration_days": 30, "prefix": "logs/"},
            {"name": "expire-tmp", "expiration_days": 7, "prefix": "tmp/"},
        ])
        rules = parse_lifecycle_rules(raw, "mybucket")
        assert rules[0] == ("cosi-mybucket-0", {
            "expiration_days": 30, "prefix": "logs/", "enabled": True,
        })
        assert rules[1] == ("expire-tmp", {
            "expiration_days": 7, "prefix": "tmp/", "enabled": True,
        })

    def test_parse_absent_or_empty(self):
        assert parse_lifecycle_rules(None, "b") == []
        assert parse_lifecycle_rules("", "b") == []
        assert parse_lifecycle_rules("[]", "b") == []

    def test_reject_invalid_json(self):
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules("{not-json", "b")
        assert ctx.value.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_reject_non_list(self):
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules('{"expiration_days": 1}', "b")
        assert "JSON array" in ctx.value.message

    def test_reject_no_action(self):
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules('[{"prefix": "x/"}]', "b")
        assert "action field" in ctx.value.message

    def test_reject_both_expiration_fields(self):
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules(
                '[{"expiration_days": 1, "expiration_date": "2026-01-01"}]', "b"
            )
        assert "cannot set both" in ctx.value.message

    def test_reject_duplicate_names(self):
        raw = json.dumps([
            {"name": "expire", "expiration_days": 30},
            {"name": "expire", "expiration_days": 7},
        ])
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules(raw, "b")
        assert "duplicate name" in ctx.value.message
        assert ctx.value.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_reject_unknown_keys(self):
        raw = json.dumps([{
            "expiration_days": 30,
            "prefix": "logs/",
            "typo_field": "nope",
        }])
        with pytest.raises(Abort) as ctx:
            parse_lifecycle_rules(raw, "b")
        assert "unknown key" in ctx.value.message
        assert "typo_field" in ctx.value.message
        assert ctx.value.code == grpc.StatusCode.INVALID_ARGUMENT


class TestCosiProvisionerSuite:
    def _create_bucket(self, name, parameters, vms_factory, extra_mocks=()):
        cosi = CosiProvisioner()
        session = vms_factory(
            ("vippools", "get_vip", "172.0.0.1"),
            ("views", "one", None),
            ("views", "create", Bunch(id=42, tenant_id=1)),
            ("users", "one", None),
            ("users", "create", None),
            ("viewpolicies", "one", Bunch(id=1, tenant_id=1, tenant_name="default")),
            ("quospolicies", "one", Bunch(id=1, tenant_id=1)),
            ("s3lifecyclerules", "ensure", Bunch(id=1)),
            *extra_mocks,
        )
        return cosi.DriverCreateBucket(name=name, parameters=parameters, vms_session=session), session

    def test_create_bucket(self, vms_session_with_mocked_resources_factory):
        """Test successful bucket creation"""
        # Preparation
        CosiProvisioner()
        bucket_name = "test-bucket"

        # Execution
        params = COMMON_PARAMS.copy()
        res, session = self._create_bucket(
            name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )

        # Assertion
        assert res.bucket_id == "test-bucket@1@http://172.0.0.1:80"
        bucket_id, tenant_id, endpoint = res.bucket_id.split("@")
        assert bucket_id == bucket_name
        assert tenant_id == "1"
        assert endpoint == "http://172.0.0.1:80"

        assert session.views.create.call_args.kwargs == {
            "bucket": "test-bucket",
            "bucket_owner": "test-bucket",
            "path": "/buckets/test-bucket",
            "protocols": ["NFS", "NFS4", "SMB", "S3"],
            "policy_id": 1,
            "tenant_id": 1,
            "qos_policy": "default",
            "s3_locks_retention_mode": "COMPILANCE",
            "s3_versioning": True,
            "s3_locks": True,
            "locking": True,
            "s3_locks_retention_period": "1d",
            "default_retention_period": "1d",
            "allow_s3_anonymous_access": True,
            "share": "test-bucket",
            "create_dir": True,
        }
        ensure_user_kwargs = session.users.create.call_args.kwargs
        assert 50000 <= ensure_user_kwargs.pop("uid") <= 60000
        assert ensure_user_kwargs == {
            "name": "test-bucket",
            'api_ver': None,
        }

    @pytest.mark.parametrize("root_export", ["", "/"])
    def test_create_bucket_with_root_storage_path(self, root_export, vms_session_with_mocked_resources_factory):
        """Test successful bucket creation with root storage path"""
        # Preparation
        common_params = COMMON_PARAMS.copy()
        common_params["root_export"] = root_export
        bucket_name = "test-bucket"

        # Execution
        res, session = self._create_bucket(
            name=bucket_name, parameters=common_params, vms_factory=vms_session_with_mocked_resources_factory
        )

        # Assertion
        create_view_kwargs = session.views.create.call_args.kwargs
        assert create_view_kwargs["path"] == "/test-bucket"


    def test_create_bucket_only_required_params(self, vms_session_with_mocked_resources_factory):
        params = dict(root_export="/buckets", vip_pool_name="vippool-1")
        bucket_name = "test-bucket"

        # Execution
        _, session = self._create_bucket(
            name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )

        # Assertion
        assert session.views.create.call_args.kwargs == {
            "path": "/buckets/test-bucket",
            "protocols": ["S3"],
            "policy_id": 1,
            "bucket": "test-bucket",
            "bucket_owner": "test-bucket",
            "tenant_id": 1,
            "create_dir": True,
        }

    @pytest.mark.parametrize("missing_param", ["root_export", "vip_pool_name"])
    def test_create_bucket_missing_required_params(self, missing_param, vms_session_with_mocked_resources_factory):
        """Test missing required parameters"""
        # Preparation
        params = COMMON_PARAMS.copy()
        del params[missing_param]
        bucket_name = "test-bucket"

        # Execution
        with pytest.raises(MissingParameter) as ex_context:
            self._create_bucket(
                name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
            )

        # Assertion
        err = ex_context.value
        assert "cannot be empty" in err.message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_create_bucket_rejects_name_longer_than_vast_max(
        self, vms_session_with_mocked_resources_factory
    ):
        """Do not silently truncate: long names must fail so Secret/status stay truthful."""
        # BucketClass(28) + UID(36) == 64 > VAST max 63
        bucket_name = "cosi-cluster-local-uscentral" + "a" * 36
        assert len(bucket_name) == 64

        with pytest.raises(Abort) as ex_context:
            self._create_bucket(
                name=bucket_name,
                parameters=COMMON_PARAMS.copy(),
                vms_factory=vms_session_with_mocked_resources_factory,
            )

        err = ex_context.value
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT
        assert "64 characters" in err.message
        assert "maximum allowed is 63" in err.message

    def test_create_bucket_with_lifecycle_rules(self, vms_session_with_mocked_resources_factory):
        params = dict(
            root_export="/buckets",
            vip_pool_name="vippool-1",
            lifecycle_rules=json.dumps([
                {"expiration_days": 30, "prefix": "logs/"},
                {"name": "expire-tmp", "expiration_days": 7, "prefix": "tmp/"},
            ]),
        )
        _, session = self._create_bucket(
            name="test-bucket",
            parameters=params,
            vms_factory=vms_session_with_mocked_resources_factory,
        )

        assert session.s3lifecyclerules.ensure.call_count == 2
        first = session.s3lifecyclerules.ensure.call_args_list[0].kwargs
        second = session.s3lifecyclerules.ensure.call_args_list[1].kwargs
        assert first == {
            "name": "cosi-test-bucket-0",
            "view_id": 42,
            "expiration_days": 30,
            "prefix": "logs/",
            "enabled": True,
        }
        assert second == {
            "name": "expire-tmp",
            "view_id": 42,
            "expiration_days": 7,
            "prefix": "tmp/",
            "enabled": True,
        }
        # lifecycle_rules must not reach views.create
        assert "lifecycle_rules" not in session.views.create.call_args.kwargs

    def test_create_bucket_without_lifecycle_rules(self, vms_session_with_mocked_resources_factory):
        params = dict(root_export="/buckets", vip_pool_name="vippool-1")
        _, session = self._create_bucket(
            name="test-bucket",
            parameters=params,
            vms_factory=vms_session_with_mocked_resources_factory,
        )
        session.s3lifecyclerules.ensure.assert_not_called()

    def test_create_bucket_bad_lifecycle_rules_skips_vms(self, vms_session_with_mocked_resources_factory):
        params = dict(
            root_export="/buckets",
            vip_pool_name="vippool-1",
            lifecycle_rules="{not-json",
        )
        session = vms_session_with_mocked_resources_factory(
            ("vippools", "get_vip", "172.0.0.1"),
            ("views", "one", None),
            ("views", "create", Bunch(id=42, tenant_id=1)),
            ("users", "one", None),
            ("users", "create", None),
            ("viewpolicies", "one", Bunch(id=1, tenant_id=1, tenant_name="default")),
            ("quospolicies", "one", Bunch(id=1, tenant_id=1)),
            ("s3lifecyclerules", "ensure", Bunch(id=1)),
        )
        with pytest.raises(Abort) as ex_context:
            CosiProvisioner().DriverCreateBucket(
                name="test-bucket", parameters=params, vms_session=session
            )
        assert ex_context.value.code == grpc.StatusCode.INVALID_ARGUMENT
        session.users.one.assert_not_called()
        session.users.create.assert_not_called()
        session.views.one.assert_not_called()
        session.views.create.assert_not_called()
        session.s3lifecyclerules.ensure.assert_not_called()

    def test_create_bucket_lifecycle_retry_after_partial_ensure(
        self, vms_session_with_mocked_resources_factory
    ):
        """COSI retry after first rule created and second ensure failed."""
        def params():
            return dict(
                root_export="/buckets",
                vip_pool_name="vippool-1",
                lifecycle_rules=json.dumps([
                    {"expiration_days": 30, "prefix": "logs/"},
                    {"name": "expire-tmp", "expiration_days": 7, "prefix": "tmp/"},
                ]),
            )

        view = Bunch(id=42, tenant_id=1)
        session = vms_session_with_mocked_resources_factory(
            ("vippools", "get_vip", "172.0.0.1"),
            ("views", "one", None),
            ("views", "create", view),
            ("users", "one", None),
            ("users", "create", Bunch(id=9, name="test-bucket")),
            ("viewpolicies", "one", Bunch(id=1, tenant_id=1, tenant_name="default")),
            ("quospolicies", "one", Bunch(id=1, tenant_id=1)),
            ("s3lifecyclerules", "ensure", Bunch(id=1)),
        )
        ensure_calls = {"n": 0}

        def ensure_side_effect(**kwargs):
            ensure_calls["n"] += 1
            if ensure_calls["n"] == 2:
                raise RuntimeError("vms failed on second lifecycle rule")
            return Bunch(id=ensure_calls["n"])

        session.s3lifecyclerules.ensure.side_effect = ensure_side_effect

        with pytest.raises(RuntimeError, match="second lifecycle rule"):
            CosiProvisioner().DriverCreateBucket(
                name="test-bucket", parameters=params(), vms_session=session
            )
        assert session.s3lifecyclerules.ensure.call_count == 2
        assert session.views.create.call_count == 1

        # Retry: user/view already exist; ensure both rules again (idempotent).
        session.views.one.return_value = view
        session.users.one.return_value = Bunch(id=9, name="test-bucket")
        session.s3lifecyclerules.ensure.side_effect = None
        session.s3lifecyclerules.ensure.return_value = Bunch(id=1)
        session.s3lifecyclerules.ensure.reset_mock()

        res = CosiProvisioner().DriverCreateBucket(
            name="test-bucket", parameters=params(), vms_session=session
        )
        assert res.bucket_id.startswith("test-bucket@1@")
        assert session.views.create.call_count == 1
        assert session.s3lifecyclerules.ensure.call_count == 2
        names = [c.kwargs["name"] for c in session.s3lifecyclerules.ensure.call_args_list]
        assert names == ["cosi-test-bucket-0", "expire-tmp"]

    def test_delete_bucket_deletes_lifecycle_rules(self, vms_session_with_mocked_resources_factory):
        view = Bunch(id=42, path="/buckets/test-bucket", tenant_id=1)
        session = vms_session_with_mocked_resources_factory(
            ("views", "one", view),
            ("s3lifecyclerules", "delete_many", None),
            ("folders", "delete", None),
            ("views", "delete_by_id", None),
            ("users", "delete", None),
        )
        order = []
        session.s3lifecyclerules.delete_many.side_effect = lambda **kw: order.append("rules")
        session.folders.delete.side_effect = lambda *a, **kw: order.append("folders")
        session.views.delete_by_id.side_effect = lambda *a, **kw: order.append("view")

        CosiProvisioner().DriverDeleteBucket(
            vms_session=session,
            bucket_id="test-bucket@1@http://172.0.0.1:80",
            delete_context=None,
        )

        session.s3lifecyclerules.delete_many.assert_called_once_with(view__id=42)
        session.views.delete_by_id.assert_called_once_with(42)
        assert order == ["rules", "folders", "view"]

    def test_delete_bucket_ok_when_lifecycle_rules_already_gone(
        self, vms_session_with_mocked_resources_factory
    ):
        """delete_many is a no-op when no rules; rest of delete still runs."""
        view = Bunch(id=42, path="/buckets/test-bucket", tenant_id=1)
        session = vms_session_with_mocked_resources_factory(
            ("views", "one", view),
            ("s3lifecyclerules", "delete_many", None),
            ("folders", "delete", None),
            ("views", "delete_by_id", None),
            ("users", "delete", None),
        )

        CosiProvisioner().DriverDeleteBucket(
            vms_session=session,
            bucket_id="test-bucket@1@http://172.0.0.1:80",
            delete_context=None,
        )

        session.s3lifecyclerules.delete_many.assert_called_once_with(view__id=42)
        session.folders.delete.assert_called_once_with("/buckets/test-bucket", 1)
        session.views.delete_by_id.assert_called_once_with(42)
        session.users.delete.assert_called_once_with(name="test-bucket")
