import json
import pytest
import grpc
from unittest.mock import MagicMock, patch
from easypy.bunch import Bunch
from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.builders.cosi import parse_create_bucket_params, parse_lifecycle_rules
from vast_csi.plugins.cosi import (
    SECRET_NAME_PARAM,
    SECRET_NAMESPACE_PARAM,
    BucketId,
    CosiProvisioner,
)

THIRTY_GIB = 30 * 1024 ** 3

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


def _view_bunch(name, root_export="/buckets", tenant_id=1, view_id=42):
    root = root_export.strip("/")
    path = f"/{root}/{name}" if root else f"/{name}"
    return Bunch(tenant_id=tenant_id, path=path, id=view_id)


class TestBucketId:
    def test_parse_ok(self):
        parsed = BucketId.parse("bkt@7@https://s3.example.com:443")
        assert parsed.name == "bkt"
        assert parsed.tenant_id == "7"
        assert parsed.endpoint == "https://s3.example.com:443"

    def test_parse_rejects_bad_format(self):
        with pytest.raises(Abort) as ctx:
            BucketId.parse("only-two@parts")
        assert ctx.value.code == grpc.StatusCode.INVALID_ARGUMENT


class TestCosiResolveSecrets:
    def test_bucket_id_uses_cosi_bucket_auth(self):
        provisioner = CosiProvisioner()
        with patch(
            "vast_csi.plugins.cosi.resolve_cosi_bucket_auth",
            return_value={"endpoint": "vms", "token": "t"},
        ) as mock_auth:
            got = provisioner.resolve_secrets({"bucket_id": "bkt@1@http://x:80"})
        assert got == {"endpoint": "vms", "token": "t"}
        mock_auth.assert_called_once_with("bkt@1@http://x:80")

    def test_parameters_secret_refs(self):
        provisioner = CosiProvisioner()
        with patch(
            "vast_csi.plugins.cosi.resolve_secret",
            return_value={"endpoint": "vms", "username": "u", "password": "p"},
        ) as mock_secret:
            got = provisioner.resolve_secrets({
                "parameters": {
                    SECRET_NAME_PARAM: "team-auth",
                    SECRET_NAMESPACE_PARAM: "app-team",
                },
            })
        assert got["username"] == "u"
        mock_secret.assert_called_once_with("team-auth", "app-team")

    def test_parameters_preferred_over_bucket_id(self):
        provisioner = CosiProvisioner()
        with patch(
            "vast_csi.plugins.cosi.resolve_secret",
            return_value={"token": "from-params"},
        ) as mock_secret, patch(
            "vast_csi.plugins.cosi.resolve_cosi_bucket_auth",
        ) as mock_auth:
            got = provisioner.resolve_secrets({
                "bucket_id": "bkt@1@http://x:80",
                "parameters": {
                    SECRET_NAME_PARAM: "team-auth",
                    SECRET_NAMESPACE_PARAM: "app-team",
                },
            })
        assert got == {"token": "from-params"}
        mock_secret.assert_called_once_with("team-auth", "app-team")
        mock_auth.assert_not_called()

    def test_bucket_id_when_parameters_have_no_secret_refs(self):
        provisioner = CosiProvisioner()
        with patch(
            "vast_csi.plugins.cosi.resolve_cosi_bucket_auth",
            return_value={"token": "from-bucket"},
        ) as mock_auth:
            got = provisioner.resolve_secrets({
                "bucket_id": "bkt@1@http://x:80",
                "parameters": {"view_policy": "default"},
            })
        assert got == {"token": "from-bucket"}
        mock_auth.assert_called_once_with("bkt@1@http://x:80")

    def test_ignores_secret_refs_outside_parameters(self):
        provisioner = CosiProvisioner()
        got = provisioner.resolve_secrets({
            "delete_context": {
                SECRET_NAME_PARAM: "nope",
                SECRET_NAMESPACE_PARAM: "nope-ns",
            },
        })
        assert got == {}

    def test_partial_secret_ref_rejected(self):
        provisioner = CosiProvisioner()
        with pytest.raises(Abort) as ctx:
            provisioner.resolve_secrets({
                "parameters": {SECRET_NAME_PARAM: "only-name"},
            })
        assert ctx.value.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_empty_without_refs(self):
        assert CosiProvisioner().resolve_secrets({"parameters": {}}) == {}


class TestParseCreateBucketParamsNamespaced:
    def test_strips_all_vastdata_com_params_from_remaining(self):
        params = parse_create_bucket_params("bucket", {
            **COMMON_PARAMS,
            "vastdata.com/secret-name": "team-auth",
            "vastdata.com/secret-namespace": "app-team",
            "cosi.vastdata.com/maxSize": "10Gi",
            "cosi.vastdata.com/unknown": "drop-me",
        })
        assert all("vastdata.com" not in k for k in params.remaining_parameters)
        assert params.requested_capacity == 10 * 1024 ** 3
        assert params.remaining_parameters["view_policy"] == "default"


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
    def _build_create_session(
        self,
        name,
        parameters,
        vms_factory,
        existing_view=None,
        existing_quota=None,
    ):
        root_export = parameters.get("root_export", "/buckets")
        view = existing_view or _view_bunch(name, root_export)
        return vms_factory(
            ("vippools", "get_vip", "172.0.0.1"),
            ("views", "one", existing_view),
            ("views", "create", view),
            ("users", "one", None),
            ("users", "create", None),
            ("viewpolicies", "one", Bunch(id=1, tenant_id=1, tenant_name="default")),
            ("quospolicies", "one", Bunch(id=1, tenant_id=1)),
            ("quotas", "one", existing_quota),
            ("quotas", "ensure", existing_quota or Bunch(id=10)),
            ("s3lifecyclerules", "ensure", Bunch(id=1)),
        )

    def _create_bucket(
        self,
        name,
        parameters,
        vms_factory,
        existing_view=None,
        existing_quota=None,
    ):
        cosi = CosiProvisioner()
        session = self._build_create_session(
            name, parameters, vms_factory, existing_view, existing_quota
        )
        return cosi.DriverCreateBucket(name=name, parameters=parameters, vms_session=session), session

    def _delete_bucket(
        self,
        bucket_id,
        vms_factory,
        view=None,
    ):
        cosi = CosiProvisioner()
        session = vms_factory(
            ("views", "one", view),
            ("globalsnapstreams", "ensure_snapshot_stream_deleted", None),
            ("snapshots", "delete", None),
            ("s3lifecyclerules", "delete_many", None),
            ("folders", "delete", None),
            ("views", "delete_by_id", None),
            ("quotas", "delete", None),
            ("users", "delete", None),
        )
        if view is None:
            session.views.one = MagicMock(return_value=None)
        return cosi.DriverDeleteBucket(
            vms_session=session,
            bucket_id=bucket_id,
            delete_context=None,
        ), session

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
        session.quotas.ensure.assert_not_called()

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

    @pytest.mark.parametrize(
        "missing_param, expected_exc, message_part",
        [
            ("root_export", MissingParameter, "cannot be empty"),
            ("vip_pool_name", Abort, "either vip_pool_name or vip_pool_fqdn"),
        ],
    )
    def test_create_bucket_missing_required_params(
        self, missing_param, expected_exc, message_part, vms_session_with_mocked_resources_factory
    ):
        """Test missing required parameters"""
        # Preparation
        params = COMMON_PARAMS.copy()
        del params[missing_param]
        bucket_name = "test-bucket"

        # Execution
        with pytest.raises(expected_exc) as ex_context:
            self._create_bucket(
                name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
            )

        # Assertion
        err = ex_context.value
        assert message_part in err.message
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

    def test_create_bucket_with_max_size(self, vms_session_with_mocked_resources_factory):
        params = COMMON_PARAMS.copy()
        params["max_size"] = "30Gi"
        bucket_name = "test-bucket"

        _, session = self._create_bucket(
            name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )

        session.quotas.ensure.assert_called_once_with(
            volume_id=bucket_name,
            view_path="/buckets/test-bucket",
            tenant_id=1,
            requested_capacity=THIRTY_GIB,
        )
        assert "max_size" not in session.views.create.call_args.kwargs

    def test_create_bucket_claim_max_size_overrides_class(self, vms_session_with_mocked_resources_factory):
        params = COMMON_PARAMS.copy()
        params["max_size"] = "30Gi"
        params["cosi.vastdata.com/maxSize"] = "5Gi"
        bucket_name = "test-bucket"
        five_gib = 5 * 1024 ** 3

        _, session = self._create_bucket(
            name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )

        session.quotas.ensure.assert_called_once_with(
            volume_id=bucket_name,
            view_path="/buckets/test-bucket",
            tenant_id=1,
            requested_capacity=five_gib,
        )
        assert "max_size" not in session.views.create.call_args.kwargs
        assert "cosi.vastdata.com/maxSize" not in session.views.create.call_args.kwargs

    def test_create_bucket_claim_max_size_only(self, vms_session_with_mocked_resources_factory):
        params = COMMON_PARAMS.copy()
        params["cosi.vastdata.com/maxSize"] = "5Gi"
        bucket_name = "test-bucket"
        five_gib = 5 * 1024 ** 3

        _, session = self._create_bucket(
            name=bucket_name, parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )

        session.quotas.ensure.assert_called_once_with(
            volume_id=bucket_name,
            view_path="/buckets/test-bucket",
            tenant_id=1,
            requested_capacity=five_gib,
        )

    @pytest.mark.parametrize("max_size", [None, ""])
    def test_create_bucket_without_max_size(self, max_size, vms_session_with_mocked_resources_factory):
        params = COMMON_PARAMS.copy()
        if max_size is not None:
            params["max_size"] = max_size
        _, session = self._create_bucket(
            name="test-bucket", parameters=params, vms_factory=vms_session_with_mocked_resources_factory
        )
        session.quotas.ensure.assert_not_called()

    @pytest.mark.parametrize("max_size", ["bogus", "0", "-1Gi"])
    def test_create_bucket_invalid_max_size(self, max_size, vms_session_with_mocked_resources_factory):
        params = COMMON_PARAMS.copy()
        params["max_size"] = max_size
        with pytest.raises(Abort) as exc:
            self._create_bucket(
                name="test-bucket", parameters=params, vms_factory=vms_session_with_mocked_resources_factory
            )
        assert exc.value.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_create_bucket_retry_same_max_size(self, vms_session_with_mocked_resources_factory):
        bucket_name = "test-bucket"
        view = _view_bunch(bucket_name)
        quota = Bunch(id=10, hard_limit=THIRTY_GIB)
        params = COMMON_PARAMS.copy()
        params["max_size"] = "30Gi"

        res, session = self._create_bucket(
            name=bucket_name,
            parameters=params,
            vms_factory=vms_session_with_mocked_resources_factory,
            existing_view=view,
            existing_quota=quota,
        )

        assert res.bucket_id.startswith(f"{bucket_name}@")
        session.quotas.ensure.assert_not_called()

    def test_create_bucket_retry_different_max_size(self, vms_session_with_mocked_resources_factory):
        bucket_name = "test-bucket"
        view = _view_bunch(bucket_name)
        quota = Bunch(id=10, hard_limit=THIRTY_GIB // 2)
        params = COMMON_PARAMS.copy()
        params["max_size"] = "30Gi"
        session = self._build_create_session(
            bucket_name,
            params,
            vms_session_with_mocked_resources_factory,
            existing_view=view,
            existing_quota=quota,
        )

        with pytest.raises(Abort) as exc:
            CosiProvisioner().DriverCreateBucket(
                name=bucket_name, parameters=params, vms_session=session
            )
        assert exc.value.code == grpc.StatusCode.ALREADY_EXISTS
        session.quotas.ensure.assert_not_called()

    def test_create_bucket_view_exists_quota_missing(self, vms_session_with_mocked_resources_factory):
        bucket_name = "test-bucket"
        view = _view_bunch(bucket_name)
        params = COMMON_PARAMS.copy()
        params["max_size"] = "30Gi"

        res, session = self._create_bucket(
            name=bucket_name,
            parameters=params,
            vms_factory=vms_session_with_mocked_resources_factory,
            existing_view=view,
            existing_quota=None,
        )

        assert res.bucket_id.startswith(f"{bucket_name}@")
        session.quotas.ensure.assert_called_once_with(
            volume_id=bucket_name,
            view_path="/buckets/test-bucket",
            tenant_id=1,
            requested_capacity=THIRTY_GIB,
        )

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
            ("globalsnapstreams", "ensure_snapshot_stream_deleted", None),
            ("snapshots", "delete", None),
            ("s3lifecyclerules", "delete_many", None),
            ("folders", "delete", None),
            ("views", "delete_by_id", None),
            ("quotas", "delete", None),
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
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        assert order == ["rules", "folders", "view"]

    def test_delete_bucket_ok_when_lifecycle_rules_already_gone(
        self, vms_session_with_mocked_resources_factory
    ):
        """delete_many is a no-op when no rules; rest of delete still runs."""
        view = Bunch(id=42, path="/buckets/test-bucket", tenant_id=1)
        session = vms_session_with_mocked_resources_factory(
            ("views", "one", view),
            ("globalsnapstreams", "ensure_snapshot_stream_deleted", None),
            ("snapshots", "delete", None),
            ("s3lifecyclerules", "delete_many", None),
            ("folders", "delete", None),
            ("views", "delete_by_id", None),
            ("quotas", "delete", None),
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
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        session.users.delete.assert_called_once_with(name="test-bucket")

    def test_delete_bucket_with_view_and_quota(self, vms_session_with_mocked_resources_factory):
        view = _view_bunch("test-bucket")
        bucket_id = "test-bucket@1@http://172.0.0.1:80"

        _, session = self._delete_bucket(
            bucket_id=bucket_id,
            vms_factory=vms_session_with_mocked_resources_factory,
            view=view,
        )

        session.s3lifecyclerules.delete_many.assert_called_once_with(view__id=view.id)
        session.folders.delete.assert_called_once_with(view.path, view.tenant_id)
        session.views.delete_by_id.assert_called_once_with(view.id)
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        session.users.delete.assert_called_once_with(name="test-bucket")

    def test_delete_bucket_with_view_no_quota(self, vms_session_with_mocked_resources_factory):
        view = _view_bunch("test-bucket")
        bucket_id = "test-bucket@1@http://172.0.0.1:80"

        _, session = self._delete_bucket(
            bucket_id=bucket_id,
            vms_factory=vms_session_with_mocked_resources_factory,
            view=view,
        )

        session.views.delete_by_id.assert_called_once_with(view.id)
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        session.users.delete.assert_called_once_with(name="test-bucket")

    def test_delete_bucket_view_gone_quota_remains(self, vms_session_with_mocked_resources_factory):
        bucket_id = "test-bucket@1@http://172.0.0.1:80"

        _, session = self._delete_bucket(
            bucket_id=bucket_id,
            vms_factory=vms_session_with_mocked_resources_factory,
            view=None,
        )

        session.views.delete_by_id.assert_not_called()
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        session.users.delete.assert_called_once_with(name="test-bucket")

    def test_delete_bucket_nothing_on_vast(self, vms_session_with_mocked_resources_factory):
        bucket_id = "test-bucket@1@http://172.0.0.1:80"

        _, session = self._delete_bucket(
            bucket_id=bucket_id,
            vms_factory=vms_session_with_mocked_resources_factory,
        )

        session.views.delete_by_id.assert_not_called()
        session.quotas.delete.assert_called_once_with(name="test-bucket")
        session.users.delete.assert_called_once_with(name="test-bucket")
