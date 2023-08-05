import pytest
from io import BytesIO
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.server import Controller
from requests import Response, Request, HTTPError
from vast_csi.exceptions import OperationNotSupported, ApiError
from easypy.semver import SemVer


class TestVmsSessionSuite:

    @pytest.mark.parametrize("cluster_version", [
        "4.3.9", "4.0.11.12", "3.4.6.123.1", "4.5.6-1"
    ])
    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.cluster_id", PropertyMock(1))
    @patch("vast_csi.vms_session.VmsSession.is_trash_api_usable", MagicMock(True))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_requisite_decorator(self, cluster_version):
        """Test `requisite` decorator produces exception when cluster version doesn't met requirements"""
        # Preparation
        cont = Controller()
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = cluster_version
        stripped_version = SemVer.loads_fuzzy(cluster_version).dumps()

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 404
            resp.raw = BytesIO(b"not found")
            req = Request()
            req.path_url = "/abc"
            raise HTTPError(response=resp, request=req)

        # Execution
        with (
                patch("vast_csi.vms_session.VmsSession.vms_info", fake_mgmt),
                patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err)
        ):
            with pytest.raises(OperationNotSupported) as exc:
                cont.vms_session.delete_folder("/abc")

        # Assertion
        assert f"Cluster does not support this operation - 'delete_folder'" \
               f" (needs 4.6.0, got {stripped_version})\n    current_version = {stripped_version}\n" \
               f"    op = delete_folder\n    required_version = 4.6.0" in exc.value.render(color=False)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.cluster_id", PropertyMock(1))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_trash_api_disabled(self):
        """Test trash api disable on cluster version >=4.6.0 cause Exception"""
        # Preparation
        cont = Controller()
        cont.vms_session.config.dont_use_trash_api = False
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = "4.6.0"

        fake_cluster_info = MagicMock(None)
        fake_cluster_info.enable_trash = False

        # Execution
        with (
                patch("vast_csi.vms_session.VmsSession.vms_info", fake_mgmt),
                patch("vast_csi.vms_session.VmsSession.cluster_info", fake_cluster_info),
        ):
            # Assertion
            assert not cont.vms_session.is_trash_api_usable()

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.cluster_id", PropertyMock(1))
    @patch("vast_csi.vms_session.VmsSession.is_trash_api_usable", MagicMock(True))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_folder_deleted_before_trash_api(self):
        """Test deleting the folder did not proceed as the folder had been manually deleted."""
        # Preparation
        cont = Controller()
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = "4.6.0"

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"no such directory")
            raise ApiError(response=resp)

        # Execution
        with (
                patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err),
                patch("vast_csi.vms_session.VmsSession.vms_info", fake_mgmt),
        ):
            is_deleted = cont.vms_session.delete_folder("/abc")

        # Assertion
        assert is_deleted is None

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.cluster_id", PropertyMock(1))
    @patch("vast_csi.vms_session.VmsSession.is_trash_api_usable", MagicMock(True))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_trash_api_disabled(self):
        """Test trash api didn't executed  as trash API is disabled on cluster."""
        # Preparation
        cont = Controller()
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = "4.6.0"

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"trash folder disabled")
            raise ApiError(response=resp)

        # Execution
        with (
                patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err),
                patch("vast_csi.vms_session.VmsSession.vms_info", fake_mgmt),
        ):
            with pytest.raises(Exception) as exc:
                is_deleted = cont.vms_session.delete_folder("/abc")

        # Assertion
        assert "Trash Folder Access is disabled" in str(exc.value)
