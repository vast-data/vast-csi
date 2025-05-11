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
    assert deserialized_session.endpoint == vms_session.endpoint
    assert deserialized_session.ssl_cert == vms_session.ssl_cert


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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name=None
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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name=None
            )


    def test_instantiate_from_user_pass(self, config, tmpdir):
        tmpdir = local.path(tmpdir)
        tmpdir.join("username").write("test")
        tmpdir.join("password").write("test")
        tmpdir.join("endpoint").write("test")
        config.vms_credentials_store = tmpdir
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name=None
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
            config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name=None
        )
        assert vms_session.token == "test"
        assert vms_session.endpoint == "test"
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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name=None
            )


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
                config=config, username=username, password=password, token=None, endpoint=endpoint, ssl_cert=None, cluster_name=None
            )

    def test_instantiate_from_user_pass(self, config):
        vms_session = VmsSession.create(
            config=config, username="test", password="test", token=None, endpoint="test", ssl_cert=None, cluster_name=None
        )
        assert vms_session.username == "test"
        assert vms_session.password == "test"
        assert vms_session.endpoint == "test"

    def test_instantiate_from_token(self, config):
        vms_session = VmsSession.create(
            config=config, username=None, password=None, token="test", endpoint="test", ssl_cert=None, cluster_name=None
        )
        assert vms_session.token == "test"
        assert vms_session.endpoint == "test"
        assert not vms_session.username
        assert not vms_session.password

    def test_ambiguous_creds(self, config):
        """Test either username/password or token should be provided, not both."""
        with pytest.raises(Exception, match="Provide either"):
            VmsSession.create(
                config=config, username="user", password="pass", token="token", endpoint="test", ssl_cert=None, cluster_name=None
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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name="clusterX"
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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
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
            config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
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
            config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name="cluster2"
        )
        assert vms_session.token == "xxxxxxxxxxxxxxxxxxxx"
        assert vms_session.endpoint == "clstr2.example.com"
        assert not vms_session.username
        assert not vms_session.password

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
                config=config, username=None, password=None, token=None, endpoint=None, ssl_cert=None, cluster_name="cluster1"
            )
