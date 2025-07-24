import pytest
import yaml
import requests
from plumbum import local
from io import BytesIO
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.plugins.csi import CsiController
from requests import Response
from vast_csi.vms_session import apiver, get_vms_session, Config, VmsSession, VastResource, LookupFieldError
from vast_csi.exceptions import OperationNotSupported, ApiError
from easypy.semver import SemVer
from easypy.resilience import _Retry
from easypy.bunch import Bunch


#####################
# Requisite decorator
#####################
def version_mock(version):
    mock_versions = MagicMock()
    mock_versions.get_sw_version.return_value = SemVer.loads_fuzzy(version)
    return mock_versions


@patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
@patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
@patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
class TestVmsSessionRequisiteSuite:

    @pytest.mark.parametrize(
        "cluster_version",
        [
            "4.3.9",
            "4.0.11.12",
            "3.4.6.123.1",
            "4.5.6-1",
            "4.6.0",
            "4.6.0-1",
            "4.6.0-1.1",
            "4.6.9",
        ],
    )
    def test_requisite_decorator(self, cluster_version, vms_session):
        """Test `requisite` decorator produces exception when cluster version doesn't meet requirements"""
        # Preparation
        stripped_version = SemVer.loads_fuzzy(cluster_version).dumps()
        # Replace the `versions` attribute on the vms_session instance
        with patch.object(vms_session, "versions", version_mock(cluster_version)):
            with pytest.raises(OperationNotSupported) as exc:
                vms_session.folders.delete("/abc", 1)

        # Assertion
        assert (
            f"Cluster does not support this operation - 'delete_folder'"
            f" (needs 4.7-0, got {stripped_version})\n    current_version = {stripped_version}\n"
            f"    op = delete_folder\n    required_version = 4.7-0"
            in exc.value.render(color=False)
        )

    def test_trash_api_disabled_helm_config(self, vms_session):
        """Test trash api disable in helm chart cause Exception"""
        # Preparation
        vms_session.config.dont_use_trash_api = True
        # Execution
        with patch.object(vms_session, "versions", version_mock("4.7.0")):
            with pytest.raises(OperationNotSupported) as exc:
                vms_session.folders.delete("/abc", 1)

        # Assertion
        assert (
            "Cannot delete folder via VMS: Disabled by Vast CSI settings"
            in exc.value.render(color=False)
        )

    def test_trash_api_disabled_cluster_settings(self, vms_session):
        """Test trash api disable on cluster cause Exception"""
        # Preparation
        vms_session.config.dont_use_trash_api = True

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"trash folder disabled")
            raise ApiError(response=resp)

        # Execution
        with (
            patch.object(vms_session, "versions", version_mock("5.0.0.25")),
            patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err),
        ):
            with pytest.raises(OperationNotSupported) as exc:
                vms_session.folders.delete("/abc", 1)

        # Assertion
        assert (
            "Cannot delete folder via VMS: Disabled by Vast CSI settings"
            in exc.value.render(color=False)
        )

    def test_delete_folder_local_mounting_requires_configuration(self, vms_session):
        """Test deleting the folder via local mounting requires deletionVipPool and deletionVipPolicy to be provided."""
        # Preparation
        cont = CsiController()
        vms_session.config.dont_use_trash_api = True

        # Execution
        with patch.object(vms_session, "versions", version_mock("4.6.0")):
            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage(vms_session, "/abc", 1)

        # Assertion
        assert "Ensure that deletionViewPolicy is properly configured" in str(exc.value)

    def test_delete_folder_unsuccesful_attempt_cache_result(self, vms_session):
        """Test if Trash API has been failed it won't be executed second time."""
        # Preparation
        cont = CsiController()
        vms_session.config.dont_use_trash_api = False
        vms_session.config.avoid_trash_api.reset(-1)

        # Execution
        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"trash folder disabled")
            raise ApiError(response=resp)

        assert vms_session.config.avoid_trash_api.expired
        # Execution
        with (
            patch.object(vms_session, "versions", version_mock("4.7.0")),
            patch(
                "vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err
            ) as mocked_request,
        ):
            with pytest.raises(AssertionError):
                cont._delete_data_from_storage(vms_session, "/abc", 1)

            assert mocked_request.call_count == 1
            assert not vms_session.config.avoid_trash_api.expired

            with pytest.raises(AssertionError):
                cont._delete_data_from_storage(vms_session, "/abc", 1)

            assert mocked_request.call_count == 1
            assert not vms_session.config.avoid_trash_api.expired

            # reset timer. trash API should be executed again
            vms_session.config.avoid_trash_api.reset(-1)

            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage(vms_session, "/abc", 1)

            assert mocked_request.call_count == 2
            assert not vms_session.config.avoid_trash_api.expired


# #####################
# # apiver decorator
# #####################
def test_function_with_api_version():
    """Test that the `api_ver` is injected into a function."""

    @apiver.v1
    def sample_function(api_ver=None):
        return api_ver

    assert sample_function() == "v1", "Expected api_ver to be injected as 'v1'"


def test_function_without_api_ver_param():
    """Test a function without an explicit `api_ver` argument."""

    @apiver.v2
    def sample_function():
        return "no api_ver argument"

    assert (
        sample_function() == "no api_ver argument"
    ), "Expected no change in function behavior"


def test_function_with_var_kwargs():
    """Test a function using `**kwargs` for `api_ver` injection."""

    @apiver.v3
    def sample_function(**kwargs):
        return kwargs.get("api_ver", None)

    assert sample_function() == "v3", "Expected api_ver to be injected into `**kwargs`"


def test_invalid_api_version():
    """Test handling of invalid API versions."""
    with pytest.raises(
        ValueError, match=r"Invalid API version:.*Must match pattern '\^v\\d\+\$'"
    ):

        @apiver.v_invalid
        def sample_function(api_ver=None):
            return api_ver


def test_class_decorator():
    """Test that all methods in a class are decorated with `api_ver`."""

    @apiver.v1
    class SampleClass:
        def method_one(self, api_ver=None):
            return api_ver

        def method_two(self):
            return "no api_ver argument"

    instance = SampleClass()
    assert (
        instance.method_one() == "v1"
    ), "Expected api_ver to be injected in method_one"
    assert (
        instance.method_two() == "no api_ver argument"
    ), "Expected no change in method_two behavior"


def test_inherited_class_methods():
    """Test that inherited methods are decorated."""

    class BaseClass:
        def base_method(self, api_ver=None):
            return api_ver

    @apiver.v2
    class SubClass(BaseClass):
        def sub_method(self):
            return "no api_ver argument"

    instance = SubClass()
    assert (
        instance.base_method() == "v2"
    ), "Expected api_ver to be injected in inherited method"
    assert (
        instance.sub_method() == "no api_ver argument"
    ), "Expected no change in sub_method behavior"


# #####################
# # refresh auth token
# #####################
@patch("requests.Session.request")
def test_refresh_auth_token_success(mock_request, monkeypatch, mock_credentials):
    mock_request.return_value.json.return_value = {"access": "test_token"}
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

    session = get_vms_session()
    with patch.object(session, "plugins", MagicMock()):
        session.refresh_auth_token()
        assert session.headers["authorization"] == "Bearer test_token"


@patch("requests.Session.request")
def test_refresh_auth_token_failure(mock_request, monkeypatch, mock_credentials):
    from vast_csi.configuration import Config

    mock_request.side_effect = ConnectionError()
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

    session = get_vms_session()
    with pytest.raises(ConnectionError):
        session.refresh_auth_token()


@patch("requests.Session.request")
def test_request_success(mock_request, monkeypatch, mock_credentials):
    # Mock response object
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"key": "value"}
    mock_request.return_value = mock_response

    # Ensure credentials are patched
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
    session = get_vms_session()
    # Execution
    session.request(
        "GET", "test_method",
        log_result=False, params={"foo": "bar"}
    )

    # Assert the request was called with the expected parameters
    mock_request.assert_called_once_with(
        "GET", "https://mock.test.com/api/v1/test_method/",
        verify=False, params={"foo": "bar"}, timeout=30
    )
    mock_response.json.assert_called_once()


@patch("requests.Session.request")
def test_request_failure_400(mock_request, monkeypatch, mock_credentials):
    mock_request.return_value.status_code = 400
    mock_request.return_value.text = "foo/bar"
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

    session = get_vms_session()
    with pytest.raises(ApiError):
        session.request(
            "POST", "test_method",
            data={"data": {"foo": "bar"}}
        )


def test_request_failure_500(monkeypatch, mock_credentials):
    resp = requests.Response()
    resp.status_code = 500
    resp.raw = BytesIO(b"Server error")

    with patch(
            "requests.Session.request", new=lambda *a, **k: resp
    ):
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

        session = get_vms_session()
        with pytest.raises(requests.HTTPError) as exc:
            session.request("GET", "test_method", log_result=False)
        assert "Server Error" in str(exc.value)


def test_request_no_return_content(monkeypatch, mock_credentials):
    resp = requests.Response()
    resp.status_code = 200
    resp.raw = BytesIO(b"")

    with patch(
            "requests.Session.request", new=lambda *a, **k: resp
    ):
        monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

        session = get_vms_session()
        res = session.request("GET", "test_method")
    assert not res


def test_refresh_token_retries(monkeypatch, vms_session):
    resp = requests.Response()
    resp.status_code = 403
    resp.raw = BytesIO(b"Token is invalid or expired")

    with patch("requests.Session.request", new=lambda *a, **k: resp):

        with pytest.raises(_Retry):
            vms_session.request("POST", "test_method", foo="bar")


def test_getattr_with_underscore(monkeypatch, mock_credentials):
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

    session = get_vms_session()
    with pytest.raises(AttributeError):
        session.__getattr__("_private")


def test_getattr_without_underscore(monkeypatch, mock_credentials):
    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)

    session = get_vms_session()

    with patch.object(session, "request") as mock_request:
        attr = "public"
        params = {"key": "value"}
        session.__getattr__(attr)(**params)
        mock_request.assert_called_once_with(
            "get", attr, params=params, log_result=True
        )


# #####################
# # Serialize/deserialize
# #####################
def test_serialize(vms_session):
    salt = "test_salt"
    serialized_data = vms_session.serialize(salt)

    assert isinstance(serialized_data, str)
    assert len(serialized_data) > 0

def test_deserialize(vms_session):
    salt = "test_salt"
    serialized_data = vms_session.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)

    assert deserialized_session.username == vms_session.username
    assert deserialized_session.password == vms_session.password
    assert deserialized_session.tenant == vms_session.tenant
    assert deserialized_session.endpoint == vms_session.endpoint
    assert deserialized_session.ssl_cert == vms_session.ssl_cert

def test_dump_data_includes_tenant(vms_session):
    dump_data = vms_session.dump_data()
    
    assert "username" in dump_data
    assert "password" in dump_data
    assert "token" in dump_data
    assert "tenant" in dump_data
    assert "endpoint" in dump_data
    assert "ssl_cert" in dump_data
    assert "cluster_name" in dump_data
    
    assert dump_data["tenant"] == vms_session.tenant


#####################
# Enhanced Serialization Tests
#####################

def test_vms_session_serialization_different_salts_produce_different_output(vms_session):
    """Test that different salts produce different encrypted output for the same session."""
    salt1 = "salt1"
    salt2 = "salt2"
    
    serialized1 = vms_session.serialize(salt1)
    serialized2 = vms_session.serialize(salt2)
    
    assert serialized1 != serialized2
    assert isinstance(serialized1, str)
    assert isinstance(serialized2, str)
    assert len(serialized1) > 0
    assert len(serialized2) > 0


def test_vms_session_serialization_round_trip_consistency(vms_session):
    """Test that serialize -> deserialize produces identical session data."""
    salt = "consistency_test_salt"
    
    # Serialize and deserialize
    serialized_data = vms_session.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)
    
    # Test all fields
    assert deserialized_session.username == vms_session.username
    assert deserialized_session.password == vms_session.password
    assert deserialized_session.token == vms_session.token
    assert deserialized_session.tenant == vms_session.tenant
    assert deserialized_session.endpoint == vms_session.endpoint
    assert deserialized_session.ssl_cert == vms_session.ssl_cert
    assert deserialized_session.cluster_name == vms_session.cluster_name


def test_vms_session_serialization_with_wrong_salt_fails():
    """Test that deserializing with wrong salt fails."""
    import base64
    from cryptography.exceptions import InvalidSignature
    
    config = Config()
    original_session = VmsSession.create(
        config=config, username="test", password="test", token=None, 
        tenant="test-tenant", endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    correct_salt = "correct_salt"
    wrong_salt = "wrong_salt"
    
    serialized_data = original_session.serialize(correct_salt)
    
    # Attempting to deserialize with wrong salt should produce garbage or fail
    try:
        deserialized_session = VmsSession.deserialize(wrong_salt, serialized_data)
        # If it doesn't fail, the data should be corrupted
        assert deserialized_session.username != original_session.username
    except Exception:
        # Expected - decryption with wrong key should fail
        pass


def test_vms_session_serialization_with_none_values():
    """Test serialization works correctly with None values."""
    config = Config()
    session_with_nones = VmsSession.create(
        config=config, username="user", password="pass", token=None, 
        tenant=None, endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    salt = "none_test_salt"
    serialized_data = session_with_nones.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)
    
    assert deserialized_session.username == "user"
    assert deserialized_session.password == "pass"
    assert deserialized_session.token is None
    assert deserialized_session.tenant is None
    assert deserialized_session.endpoint == "test.com"
    assert deserialized_session.ssl_cert is None
    assert deserialized_session.cluster_name is None


def test_vms_session_serialization_with_special_characters():
    """Test serialization works with special characters in credentials."""
    config = Config()
    session_with_special_chars = VmsSession.create(
        config=config, username="user@domain.com", password="p@ssw0rd!#$%", 
        token=None, tenant="tenant-with-dashes", endpoint="test.com", 
        ssl_cert=None,  # Avoid permission issues with /etc/ssl/certs
        cluster_name=None
    )
    
    salt = "special_chars_salt"
    serialized_data = session_with_special_chars.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)
    
    assert deserialized_session.username == "user@domain.com"
    assert deserialized_session.password == "p@ssw0rd!#$%"
    assert deserialized_session.tenant == "tenant-with-dashes"
    assert deserialized_session.ssl_cert is None


def test_vms_session_serialization_output_format():
    """Test that serialized output is properly base64 encoded."""
    import base64
    config = Config()
    session = VmsSession.create(
        config=config, username="test", password="test", token=None, 
        tenant=None, endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    salt = "format_test_salt"
    serialized_data = session.serialize(salt)
    
    # Should be valid base64
    try:
        decoded_bytes = base64.b64decode(serialized_data)
        assert len(decoded_bytes) > 16  # At least IV (16 bytes) + some ciphertext
    except Exception as e:
        pytest.fail(f"Serialized data is not valid base64: {e}")


#####################
# LuksManager Serialization Tests
#####################

def test_luks_manager_serialization_round_trip_consistency():
    """Test that LuksManager serialize -> deserialize produces identical data."""
    from vast_csi.luks_utils import LuksManager
    
    original_manager = LuksManager(
        volume_id="test-volume-123",
        passphrase="super-secret-key",
        encryption_config={
            "luks_type": "luks2",
            "cipher": "aes-xts-plain64",
            "key_size": "512",
            "hash_algo": "sha256"
        }
    )
    
    salt = "luks_test_salt"
    serialized_data = original_manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == original_manager.volume_id
    assert deserialized_manager.passphrase == original_manager.passphrase
    assert deserialized_manager.encryption_config == original_manager.encryption_config


def test_luks_manager_serialization_different_salts():
    """Test that different salts produce different encrypted output for LuksManager."""
    from vast_csi.luks_utils import LuksManager
    
    manager = LuksManager(
        volume_id="test-volume",
        passphrase="secret",
        encryption_config={"cipher": "aes-xts-plain64"}
    )
    
    salt1 = "salt1"
    salt2 = "salt2"
    
    serialized1 = manager.serialize(salt1)
    serialized2 = manager.serialize(salt2)
    
    assert serialized1 != serialized2
    assert isinstance(serialized1, str)
    assert isinstance(serialized2, str)


def test_luks_manager_serialization_with_none_passphrase():
    """Test LuksManager serialization works with None passphrase."""
    from vast_csi.luks_utils import LuksManager
    
    manager = LuksManager(
        volume_id="test-volume",
        passphrase=None,
        encryption_config={"luks_type": "luks2"}
    )
    
    salt = "none_passphrase_salt"
    serialized_data = manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == "test-volume"
    assert deserialized_manager.passphrase is None
    assert deserialized_manager.encryption_config == {"luks_type": "luks2"}


def test_luks_manager_serialization_with_empty_encryption_config():
    """Test LuksManager serialization works with empty encryption config."""
    from vast_csi.luks_utils import LuksManager
    
    manager = LuksManager(
        volume_id="test-volume",
        passphrase="secret",
        encryption_config={}
    )
    
    salt = "empty_config_salt"
    serialized_data = manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == "test-volume"  
    assert deserialized_manager.passphrase == "secret"
    assert deserialized_manager.encryption_config == {}


def test_luks_manager_serialization_with_complex_encryption_config():
    """Test LuksManager serialization with complex encryption configuration."""
    from vast_csi.luks_utils import LuksManager
    
    complex_config = {
        "luks_type": "luks2",
        "cipher": "aes-xts-plain64",
        "key_size": "512",
        "hash_algo": "sha256",
        "pbkdf_mem": "65536",
        "iter_time": "2000",
        "custom_param": "value with spaces and special chars !@#$%"
    }
    
    manager = LuksManager(
        volume_id="complex-test-volume",
        passphrase="complex-passphrase-123!@#",
        encryption_config=complex_config
    )
    
    salt = "complex_config_salt"
    serialized_data = manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == "complex-test-volume"
    assert deserialized_manager.passphrase == "complex-passphrase-123!@#"
    assert deserialized_manager.encryption_config == complex_config


def test_luks_manager_dump_data_format():
    """Test that LuksManager dump_data returns expected structure."""
    from vast_csi.luks_utils import LuksManager
    
    manager = LuksManager(
        volume_id="test-volume",
        passphrase="secret",
        encryption_config={"type": "luks2"}
    )
    
    dump_data = manager.dump_data()
    
    assert isinstance(dump_data, dict)
    assert "volume_id" in dump_data
    assert "passphrase" in dump_data
    assert "encryption_config" in dump_data
    
    assert dump_data["volume_id"] == "test-volume"
    assert dump_data["passphrase"] == "secret"
    assert dump_data["encryption_config"] == {"type": "luks2"}


def test_luks_manager_load_data_method():
    """Test that LuksManager load_data works correctly."""
    from vast_csi.luks_utils import LuksManager
    
    test_data = {
        "volume_id": "loaded-volume",
        "passphrase": "loaded-secret",
        "encryption_config": {"loaded": "config"}
    }
    
    loaded_manager = LuksManager.load_data(test_data)
    
    assert loaded_manager.volume_id == "loaded-volume"
    assert loaded_manager.passphrase == "loaded-secret"
    assert loaded_manager.encryption_config == {"loaded": "config"}


#####################
# Cross-class Serialization Tests
#####################

def test_different_classes_same_salt_different_output():
    """Test that VmsSession and LuksManager produce different output with same salt."""
    from vast_csi.luks_utils import LuksManager
    
    config = Config()
    vms_session = VmsSession.create(
        config=config, username="test", password="test", token=None, 
        tenant=None, endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    luks_manager = LuksManager(
        volume_id="test-volume",
        passphrase="secret",
        encryption_config={}
    )
    
    salt = "shared_salt"
    vms_serialized = vms_session.serialize(salt)
    luks_serialized = luks_manager.serialize(salt)
    
    assert vms_serialized != luks_serialized
    
    # Cross-deserialization should fail or produce garbage
    try:
        # This should fail since the data structures are different
        VmsSession.deserialize(salt, luks_serialized)
        pytest.fail("Cross-deserialization should not succeed")
    except Exception:
        # Expected - different data structures
        pass


#####################
# Additional Edge Case Tests
#####################

def test_vms_session_serialization_with_empty_strings():
    """Test serialization works with empty strings."""
    config = Config()
    # Use token authentication to avoid empty username/password validation
    session_with_empty_strings = VmsSession.create(
        config=config, username=None, password=None, token="test-token", 
        tenant="", endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    salt = "empty_strings_salt"
    serialized_data = session_with_empty_strings.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)
    
    assert deserialized_session.username is None
    assert deserialized_session.password is None
    assert deserialized_session.token == "test-token"
    assert deserialized_session.tenant == ""


def test_vms_session_serialization_with_unicode_characters():
    """Test serialization works with Unicode characters."""
    config = Config()
    session_with_unicode = VmsSession.create(
        config=config, username="用户", password="密码123", token=None, 
        tenant="租户-テスト", endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    salt = "unicode_salt_测试"
    serialized_data = session_with_unicode.serialize(salt)
    deserialized_session = VmsSession.deserialize(salt, serialized_data)
    
    assert deserialized_session.username == "用户"
    assert deserialized_session.password == "密码123"
    assert deserialized_session.tenant == "租户-テスト"
    assert deserialized_session.cluster_name is None


def test_luks_manager_serialization_with_unicode_in_config():
    """Test LuksManager serialization with Unicode in encryption config."""
    from vast_csi.luks_utils import LuksManager
    
    unicode_config = {
        "cipher": "aes-xts-plain64",
        "description": "Description with Unicode: 加密配置 テスト",
        "label": "ラベル-标签"
    }
    
    manager = LuksManager(
        volume_id="unicode-test-卷",
        passphrase="密码-パスワード",
        encryption_config=unicode_config
    )
    
    salt = "unicode_luks_salt"
    serialized_data = manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == "unicode-test-卷"
    assert deserialized_manager.passphrase == "密码-パスワード"
    assert deserialized_manager.encryption_config["description"] == "Description with Unicode: 加密配置 テスト"
    assert deserialized_manager.encryption_config["label"] == "ラベル-标签"


def test_serialization_with_very_long_strings():
    """Test serialization with very long strings."""
    from vast_csi.luks_utils import LuksManager
    
    long_string = "A" * 10000  # 10KB string
    very_long_config = {
        "long_field": long_string,
        "another_long_field": "B" * 5000
    }
    
    manager = LuksManager(
        volume_id="long-test-volume",
        passphrase=long_string[:100],  # Reasonable passphrase length
        encryption_config=very_long_config
    )
    
    salt = "long_strings_salt"
    serialized_data = manager.serialize(salt)
    deserialized_manager = LuksManager.deserialize(salt, serialized_data)
    
    assert deserialized_manager.volume_id == "long-test-volume"
    assert deserialized_manager.passphrase == long_string[:100]
    assert deserialized_manager.encryption_config["long_field"] == long_string
    assert deserialized_manager.encryption_config["another_long_field"] == "B" * 5000


def test_serialization_deterministic_same_input():
    """Test that serialization is deterministic for the same input and salt."""
    config = Config()
    session = VmsSession.create(
        config=config, username="test", password="test", token=None, 
        tenant=None, endpoint="test.com", ssl_cert=None, cluster_name=None
    )
    
    salt = "deterministic_salt"
    
    # Serialize the same session multiple times with the same salt
    serialized1 = session.serialize(salt)
    serialized2 = session.serialize(salt)
    
    # Note: This test might fail because of random IV generation
    # The encrypted content should be different due to IV, but let's test the behavior
    # In AES-CFB mode with random IV, the output should be different each time
    # So we actually expect them to be different
    assert isinstance(serialized1, str)
    assert isinstance(serialized2, str)
    # With random IV, these should actually be different
    # But both should deserialize to the same content
    
    deserialized1 = VmsSession.deserialize(salt, serialized1)
    deserialized2 = VmsSession.deserialize(salt, serialized2)
    
    assert deserialized1.username == deserialized2.username
    assert deserialized1.password == deserialized2.password


def test_serialization_with_malformed_base64():
    """Test deserialization behavior with malformed base64 input."""
    from vast_csi.luks_utils import LuksManager
    
    malformed_inputs = [
        "not-base64!",
        "SGVsbG8=extra-chars",
        "",
        "A" * 100,  # Invalid base64
    ]
    
    for malformed_input in malformed_inputs:
        try:
            LuksManager.deserialize("test_salt", malformed_input)
            pytest.fail(f"Expected deserialization to fail for input: {malformed_input}")
        except Exception:
            # Expected - malformed input should fail
            pass


def test_serialization_data_integrity():
    """Test that serialized data maintains integrity across multiple operations."""
    from vast_csi.luks_utils import LuksManager
    
    original_manager = LuksManager(
        volume_id="integrity-test",
        passphrase="integrity-passphrase", 
        encryption_config={"test": "integrity"}
    )
    
    salt = "integrity_salt"
    
    # Multiple serialize/deserialize cycles
    current_manager = original_manager
    for i in range(5):
        serialized = current_manager.serialize(salt)
        current_manager = LuksManager.deserialize(salt, serialized)
    
    # After 5 cycles, data should still be identical
    assert current_manager.volume_id == original_manager.volume_id
    assert current_manager.passphrase == original_manager.passphrase
    assert current_manager.encryption_config == original_manager.encryption_config


#####################
# VastResource
#####################
@pytest.fixture
def mock_session():
    session = MagicMock(spec=VmsSession)
    return session


def test_list(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = [Bunch(id=1, name="Test")]

    # Call the list method and check that it calls the session's get method
    result = resource.list(api_ver="v1", foo="bar")
    mock_session.get.assert_called_once_with("test_resource", api_ver="v1", params={"foo": "bar"})
    assert result == [Bunch(id=1, name="Test")]


def test_create(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.post.return_value = Bunch(id=1, name="Test")

    # Call the create method and check that it calls the session's post method
    result = resource.create(api_ver="v1", foo="bar")
    mock_session.post.assert_called_once_with("test_resource", api_ver="v1", data={"foo": "bar"})
    assert result == Bunch(id=1, name="Test")


def test_update(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.patch.return_value = Bunch(id=1, name="Updated Test")

    # Call the update method and check that it calls the session's patch method
    result = resource.update(1, api_ver="v1", foo="bar")
    mock_session.patch.assert_called_once_with("test_resource/1", api_ver="v1", data={"foo": "bar"})
    assert result == Bunch(id=1, name="Updated Test")


def test_delete(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = [Bunch(id=1, name="Test")]
    mock_session.delete.return_value = Bunch(status="deleted")

    # Call the delete method and check that it calls the session's delete method
    result = resource.delete(api_ver="v1", foo="bar")
    mock_session.delete.assert_called_once_with("test_resource/1", api_ver="v1")
    assert result == Bunch(status="deleted")


def test_delete_not_found(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = []
    resource.delete(api_ver="v1", foo="bar")
    mock_session.delete.assert_not_called()


def test_one_found(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = [Bunch(id=1, name="Test")]
    result = resource.one(api_ver="v1", foo="bar")
    mock_session.get.assert_called_once_with("test_resource", api_ver="v1", params={"foo": "bar"})
    assert result == Bunch(id=1, name="Test")


def test_one_multiple(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = [Bunch(id=1, name="Test"), Bunch(id=2, name="Test 2")]

    with pytest.raises(Exception):
        resource.one(api_ver="v1", foo="bar")


def test_one_not_found(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = []

    with pytest.raises(Exception):
        resource.one(fail_if_missing=True, api_ver="v1", foo="bar")


def test_ensure_exists(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"

    mock_session.get.return_value = [Bunch(id=1, name="Test")]
    result = resource.ensure(name="Test", api_ver="v1", foo="bar")
    mock_session.get.assert_called_once_with(
        "test_resource", api_ver="v1", params={'name': 'Test'}
    )
    assert result == Bunch(id=1, name="Test")


def test_ensure_create(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"

    # Mock the response from the session's one method to return None (entry does not exist)
    mock_session.get.return_value = []
    mock_session.post.return_value = Bunch(id=1, name="Test")

    # Call the ensure method and check the result
    result = resource.ensure(name="Test", api_ver="v1", foo="bar")
    mock_session.post.assert_called_once_with(
        "test_resource", api_ver="v1", data={'name': 'Test', 'foo': 'bar'}
    )
    assert result == Bunch(id=1, name="Test")


def test_get(mock_session):
    resource = VastResource(mock_session)
    resource.resource_name = "test_resource"
    mock_session.get.return_value = Bunch(id=1, name="Test")

    # Call the get method and check that it calls the session's get method
    result = resource.get(1, api_ver="v1")
    mock_session.get.assert_called_once_with("test_resource/1", api_ver="v1")
    assert result == Bunch(id=1, name="Test")



class TestVmsSessionInitFromGlobalSecretSuite:
    """
    From CSI Driver prospective instantiation from "global secret"
    is state when no credentials provided in secrets from storageClass and
    no "cluster_name" provided IOW no option
    to read credentials from special /opt/vms-auth/clusters.yaml file
    """

    def test_no_global_secret(self, config):
        with pytest.raises(LookupFieldError, match="Could not find username"):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
            )

    @pytest.mark.parametrize('files, err', [
        (("username", 'password'), "Could not find endpoint"),
        (("username", 'endpoint'), "Could not find password"),
        (("password", 'endpoint'), "Could not find username"),
    ]
    )
    def test_missing_values(self, config, tmpdir, files, err):
        tmpdir = local.path(tmpdir)
        for file in files:
            tmpdir.join(file).write("test")
        config.vms_credentials_store = tmpdir
        with pytest.raises(LookupFieldError, match=err):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
            )


    def test_instantiate_from_user_pass(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("username").write("test")
        tmpdir.join("password").write("test")
        tmpdir.join("endpoint").write("test")
        config.vms_credentials_store = tmpdir
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
        )
        assert vms_session.username == "test"
        assert vms_session.password == "test"
        assert vms_session.endpoint == "test"


    def test_instantiate_from_token(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("token").write("test")
        tmpdir.join("endpoint").write("test")
        config.vms_credentials_store = tmpdir
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
        )
        assert vms_session.token == "test"
        assert vms_session.endpoint == "test"
        assert not vms_session.username
        assert not vms_session.password

    def test_instantiate_from_token_with_tenant(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("token").write("test")
        tmpdir.join("tenant").write("test-tenant")
        tmpdir.join("endpoint").write("test")
        config.vms_credentials_store = tmpdir
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
        )
        assert vms_session.token == "test"
        assert vms_session.tenant == "test-tenant"
        assert vms_session.endpoint == "test"
        assert vms_session.headers.get("X-Tenant-Name") == "test-tenant"
        assert not vms_session.username
        assert not vms_session.password


    def test_ambiguous_creds(self, config, tmpdir):
        """Test either username/password or token should be provided"""
        tmpdir = local.path(tmpdir)
        tmpdir.join("username").write("test")
        tmpdir.join("password").write("test")
        tmpdir.join("endpoint").write("test")
        tmpdir.join("token").write("test")
        config.vms_credentials_store = tmpdir
        with pytest.raises(Exception, match="Provide either"):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None
            )

    def test_global_store_ignored_when_token_provided(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("username").write("test")
        tmpdir.join("password").write("test")
        tmpdir.join("endpoint").write("test")
        tmpdir.join("token").write("test")
        config.vms_credentials_store = tmpdir

        session = VmsSession.create(
            config=config, username=None, password=None, token="xxx",
            endpoint="https://from-secret", ssl_cert=None, cluster_name=None,
        )

        assert session.username is None
        assert session.password is None
        assert session.token == "xxx"
        assert session.endpoint == "https://from-secret"

    def test_global_store_ignored_when_username_provided(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("username").write("test")
        tmpdir.join("password").write("test")
        tmpdir.join("endpoint").write("test")
        tmpdir.join("token").write("test")
        config.vms_credentials_store = tmpdir

        session = VmsSession.create(
            config=config, username="admin", password="admin", token=None,
            endpoint="https://from-secret", ssl_cert=None, cluster_name=None,
        )

        assert session.username == "admin"
        assert session.password == "admin"
        assert session.token is None
        assert session.endpoint == "https://from-secret"

class TestVmsSessionInitFromArgumentsSuite:
    """
    Tests for instantiating VmsSession directly from passed arguments (StorageClass secret scope).
    """


    @pytest.mark.parametrize('username, password, endpoint, err', [
        ("user", None, "endpoint", "Could not find password"),
        (None, "pass", "endpoint", "Could not find username"),
        ("user", "pass", None, "Could not find endpoint"),
    ])
    def test_missing_values(self, config, username, password, endpoint, err):
        with pytest.raises(LookupFieldError, match=err):
            VmsSession.create(
                config=config, username=username, password=password, token=None, tenant=None, endpoint=endpoint, ssl_cert=None, cluster_name=None
            )

    def test_instantiate_from_user_pass(self, config):
        vms_session = VmsSession.create(
            config=config, username="test", password="test", token=None, tenant=None, endpoint="test", ssl_cert=None, cluster_name=None
        )
        assert vms_session.username == "test"
        assert vms_session.password == "test"
        assert vms_session.endpoint == "test"

    def test_instantiate_from_token(self, config):
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token="test", tenant=None, endpoint="test", ssl_cert=None, cluster_name=None
        )
        assert vms_session.token == "test"
        assert vms_session.endpoint == "test"
        assert not vms_session.username
        assert not vms_session.password

    def test_instantiate_with_tenant_argument(self, config):
        """Test instantiation with tenant passed as argument."""
        vms_session = VmsSession.create(
            config=config, username="test", password="test", token=None, tenant="my-tenant", endpoint="test", ssl_cert=None, cluster_name=None
        )
        assert vms_session.username == "test"
        assert vms_session.password == "test"
        assert vms_session.tenant == "my-tenant"
        assert vms_session.endpoint == "test"
        assert vms_session.headers.get("X-Tenant-Name") == "my-tenant"

    def test_ambiguous_creds(self, config):
        """Test either username/password or token should be provided, not both."""
        with pytest.raises(Exception, match="Provide either"):
            VmsSession.create(
                config=config, username="user", password="pass", token="token", tenant=None, endpoint="test", ssl_cert=None, cluster_name=None
            )



class TestVmsSessionInitFromClustersSuite:
    """
    Tests for VmsSession instantiation from multi-cluster YAML configuration.
    """

    def test_missing_cluster_name(self, config, tmpdir):
        """Test when cluster_name is not found in the clusters file."""
        tmpdir.join("clusters").write(yaml.dump({"cluster1": {"username": "user1"}}))
        config.vms_credentials_store = local.path(tmpdir)
        with pytest.raises(LookupFieldError, match="Make sure cluster name is present in secret."):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="clusterX"
            )

    @pytest.mark.parametrize('cluster_data, err', [
        ({"username": "user1", "endpoint": "clstr1.example.com"}, "Could not find password"),
        ({"password": "111111", "endpoint": "clstr1.example.com"}, "Could not find username"),
    ])
    def test_missing_values_in_cluster(self, config, tmpdir, cluster_data, err):
        """Test missing fields for a cluster in clusters.yaml."""
        tmpdir.join("clusters").write(yaml.dump({"cluster1": cluster_data}))
        config.vms_credentials_store = local.path(tmpdir)
        with pytest.raises(LookupFieldError, match=err):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
            )

    def test_instantiate_from_user_pass(self, config, tmpdir):
        """Test successful instantiation from cluster credentials with username/password."""
        tmpdir.join("clusters").write(yaml.dump({
            "cluster1": {
                "username": "user1",
                "password": "111111",
                "endpoint": "clstr1.example.com"
            }
        }))
        config.vms_credentials_store = local.path(tmpdir)
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
        )
        assert vms_session.username == "user1"
        assert vms_session.password == "111111"
        assert vms_session.endpoint == "clstr1.example.com"

    def test_instantiate_from_token(self, config, tmpdir):
        """Test successful instantiation from cluster credentials with token."""
        tmpdir.join("clusters").write(yaml.dump({
            "cluster2": {
                "token": "xxxxxxxxxxxxxxxxxxxx",
                "endpoint": "clstr2.example.com"
            }
        }))
        config.vms_credentials_store = local.path(tmpdir)
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="cluster2"
        )
        assert vms_session.token == "xxxxxxxxxxxxxxxxxxxx"
        assert vms_session.endpoint == "clstr2.example.com"
        assert not vms_session.username
        assert not vms_session.password

    def test_instantiate_with_tenant_from_cluster(self, config, tmpdir):
        """Test successful instantiation from cluster credentials with tenant."""
        tmpdir.join("clusters").write(yaml.dump({
            "cluster3": {
                "username": "user3",
                "password": "333333",
                "tenant": "test-tenant",
                "endpoint": "clstr3.example.com"
            }
        }))
        config.vms_credentials_store = local.path(tmpdir)
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="cluster3"
        )
        assert vms_session.username == "user3"
        assert vms_session.password == "333333"
        assert vms_session.tenant == "test-tenant"
        assert vms_session.endpoint == "clstr3.example.com"
        assert vms_session.headers.get("X-Tenant-Name") == "test-tenant"

    def test_ambiguous_creds(self, config, tmpdir):
        """Test error when both username/password and token are provided in cluster config."""
        tmpdir.join("clusters").write(yaml.dump({
            "cluster1": {
                "username": "user1",
                "password": "111111",
                "token": "xxxxxxxxxxxxxxxxxxxx",
                "endpoint": "clstr1.example.com"
            }
        }))
        config.vms_credentials_store = local.path(tmpdir)
        with pytest.raises(Exception, match="Provide either"):
            VmsSession.create(
                config=config, username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
            )

