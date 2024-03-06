import pytest
import grpc
from easypy.bunch import Bunch
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.server import CosiProvisioner, Abort, MissingParameter


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


@patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
@patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
@patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
@patch("vast_csi.vms_session.VmsSession.get_vip", MagicMock(return_value="172.0.0.1"))
@patch("vast_csi.vms_session.VmsSession.get_view", MagicMock(return_value=None))
@patch(
    "vast_csi.vms_session.VmsSession.get_view_policy",
    MagicMock(return_value=Bunch(id=1, tenant_id=1, tenant_name="default")),
)
@patch(
    "vast_csi.vms_session.VmsSession.get_qos_policy",
    MagicMock(return_value=Bunch(id=1, tenant_id=1)),
)
class TestCosiProvisionerSuite:
    def _create_bucket(self, name, parameters):
        cosi = CosiProvisioner()
        return cosi.DriverCreateBucket(name=name, parameters=parameters)

    @patch("vast_csi.vms_session.VmsSession.ensure_user")
    @patch("vast_csi.vms_session.VmsSession.create_view")
    def test_create_bucket(self, m_create_view, m_ensure_user):
        """Test successful bucket creation"""
        # Preparation
        cosi = CosiProvisioner()
        bucket_name = "test-bucket"
        m_create_view.return_value = Bunch(tenant_id=1)

        # Execution
        params = COMMON_PARAMS.copy()
        res = self._create_bucket(name=bucket_name, parameters=params)

        # Assertion
        assert res.bucket_id == "test-bucket@1@http://172.0.0.1:80"
        bucket_id, tenant_id, endpoint = res.bucket_id.split("@")
        assert bucket_id == bucket_name
        assert tenant_id == "1"
        assert endpoint == "http://172.0.0.1:80"

        assert m_create_view.call_args.kwargs == {
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
        }
        ensure_user_kwargs = m_ensure_user.call_args.kwargs
        assert 50000 <= ensure_user_kwargs.pop("uid") <= 60000
        assert ensure_user_kwargs == {
            "name": "test-bucket",
            "allow_create_bucket": True,
        }

    @pytest.mark.parametrize("root_export", ["", "/"])
    @patch("vast_csi.vms_session.VmsSession.ensure_user", MagicMock())
    @patch("vast_csi.vms_session.VmsSession.create_view")
    def test_create_bucket_with_root_storage_path(self, m_create_view, root_export):
        """Test successful bucket creation with root storage path"""
        # Preparation
        common_params = COMMON_PARAMS.copy()
        common_params["root_export"] = root_export
        bucket_name = "test-bucket"

        # Execution
        res = self._create_bucket(name=bucket_name, parameters=common_params)

        # Assertion
        create_view_kwargs = m_create_view.call_args.kwargs
        assert create_view_kwargs["path"] == "/test-bucket"

    @patch("vast_csi.vms_session.VmsSession.ensure_user", MagicMock())
    @patch("vast_csi.vms_session.VmsSession.create_view")
    def test_create_bucket_only_required_params(self, m_create_view):
        params = dict(root_export="/buckets", vip_pool_name="vippool-1")
        bucket_name = "test-bucket"

        # Execution
        self._create_bucket(name=bucket_name, parameters=params)

        # Assertion
        assert m_create_view.call_args.kwargs == {
            "path": "/buckets/test-bucket",
            "protocols": ["S3"],
            "policy_id": 1,
            "bucket": "test-bucket",
            "bucket_owner": "test-bucket",
            "tenant_id": 1,
        }

    @pytest.mark.parametrize("missing_param", ["root_export", "vip_pool_name"])
    def test_create_bucket_missing_required_params(self, missing_param):
        """Test missing required parameters"""
        # Preparation
        params = COMMON_PARAMS.copy()
        del params[missing_param]
        bucket_name = "test-bucket"

        # Execution
        with pytest.raises(MissingParameter) as ex_context:
            self._create_bucket(name=bucket_name, parameters=params)

        # Assertion
        err = ex_context.value
        assert "cannot be empty" in err.message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT
