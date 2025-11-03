import pytest
import grpc
from easypy.bunch import Bunch
from vast_csi.plugins.cosi import CosiProvisioner, MissingParameter


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


class TestCosiProvisionerSuite:
    def _create_bucket(self, name, parameters, vms_factory):
        cosi = CosiProvisioner()
        session = vms_factory(
            ("vippools", "get_vip", "172.0.0.1"),
            ("views", "one", None),
            ("views", "create",  Bunch(tenant_id=1)),
            ("users", "one",  None),
            ("users", "create",  None),
            ("viewpolicies", "one", Bunch(id=1, tenant_id=1, tenant_name="default")),
            ("quospolicies", "one", Bunch(id=1, tenant_id=1)),
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
