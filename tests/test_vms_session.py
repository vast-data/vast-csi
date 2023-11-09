import pytest
from io import BytesIO
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.server import Controller
from requests import Response, Request, HTTPError
from vast_csi.exceptions import OperationNotSupported, ApiError
from easypy.semver import SemVer


class TestVmsSessionSuite:

    @pytest.mark.parametrize("cluster_version", [
        "4.3.9", "4.0.11.12", "3.4.6.123.1", "4.5.6-1", "4.6.0", "4.6.0-1", "4.6.0-1.1", "4.6.9"
    ])
    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_requisite_decorator(self, cluster_version):
        """Test `requisite` decorator produces exception when cluster version doesn't met requirements"""
        # Preparation
        cont = Controller()
        fake_mgmt = PropertyMock(return_value=SemVer.loads_fuzzy(cluster_version))
        stripped_version = SemVer.loads_fuzzy(cluster_version).dumps()

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 404
            resp.raw = BytesIO(b"not found")
            req = Request()
            req.path_url = "/abc"
            raise HTTPError(response=resp, request=req)

        # Execution
        with patch("vast_csi.vms_session.VmsSession.sw_version", fake_mgmt):
            with pytest.raises(OperationNotSupported) as exc:
                cont.vms_session.delete_folder("/abc", 1)

        # Assertion
        assert f"Cluster does not support this operation - 'delete_folder'" \
               f" (needs 4.7-0, got {stripped_version})\n    current_version = {stripped_version}\n" \
               f"    op = delete_folder\n    required_version = 4.7-0" in exc.value.render(color=False)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_trash_api_disabled_helm_config(self):
        """Test trash api disable in helm chart cause Exception"""
        # Preparation
        cont = Controller()
        cont.vms_session.config.dont_use_trash_api = True
        fake_mgmt = PropertyMock(return_value=SemVer.loads_fuzzy("4.7.0"))

        # Execution
        with patch("vast_csi.vms_session.VmsSession.sw_version", fake_mgmt):
            with pytest.raises(OperationNotSupported) as exc:
                cont.vms_session.delete_folder("/abc", 1)

        # Assertion
        assert "Cannot delete folder via VMS: Disabled by Vast CSI settings" in exc.value.render(color=False)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_trash_api_disabled_cluster_settings(self):
        """Test trash api disable on cluster cause Exception"""
        # Preparation
        cont = Controller()
        cont.vms_session.config.dont_use_trash_api = True
        fake_mgmt = PropertyMock(return_value=SemVer.loads_fuzzy("5.0.0.25"))

        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"trash folder disabled")
            raise ApiError(response=resp)

        # Execution
        with (
            patch("vast_csi.vms_session.VmsSession.sw_version", fake_mgmt),
            patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err),
        ):
            with pytest.raises(OperationNotSupported) as exc:
                cont.vms_session.delete_folder("/abc", 1)

        # Assertion
        assert "Cannot delete folder via VMS: Disabled by Vast CSI settings" in exc.value.render(color=False)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_delete_folder_local_mounting_requires_configuration(self):
        """Test deleting the folder via local mounting requires deletionVipPool and deletionVipPolicy to be provided."""
        # Preparation
        cont = Controller()
        cont.vms_session.config.dont_use_trash_api = True
        fake_mgmt = PropertyMock(return_value=SemVer.loads_fuzzy("4.6.0"))

        # Execution
        with patch("vast_csi.vms_session.VmsSession.sw_version", fake_mgmt):
            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage("/abc", 1)

        # Assertion
        assert "Ensure that deletionVipPool and deletionViewPolicy are properly configured" in str(exc.value)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_delete_folder_unsuccesful_attempt_cache_result(self):
        """Test if Trash API has been failed it wont be executed second time."""
        # Preparation
        cont = Controller()
        cont.vms_session.config.dont_use_trash_api = False
        cont.vms_session.config.avoid_trash_api.reset(-1)
        fake_mgmt = PropertyMock(return_value=SemVer.loads_fuzzy("4.7.0"))

        # Execution
        def raise_http_err(*args, **kwargs):
            resp = Response()
            resp.status_code = 400
            resp.raw = BytesIO(b"trash folder disabled")
            raise ApiError(response=resp)

        assert cont.vms_session.config.avoid_trash_api.expired
        # Execution
        with (
            patch("vast_csi.vms_session.VmsSession.sw_version", fake_mgmt),
            patch("vast_csi.vms_session.VmsSession.delete", side_effect=raise_http_err) as mocked_request,
        ):
            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage("/abc", 1)

            assert mocked_request.call_count == 1
            assert not cont.vms_session.config.avoid_trash_api.expired

            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage("/abc", 1)

            assert mocked_request.call_count == 1
            assert not cont.vms_session.config.avoid_trash_api.expired

            # reset timer. trash API should be executed again
            cont.vms_session.config.avoid_trash_api.reset(-1)

            with pytest.raises(AssertionError) as exc:
                cont._delete_data_from_storage("/abc", 1)

            assert mocked_request.call_count == 2
            assert not cont.vms_session.config.avoid_trash_api.expired
