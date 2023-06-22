import pytest
from io import BytesIO
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.server import Controller
from requests import Response, Request, HTTPError
from vast_csi.exceptions import OperationNotSupported
from easypy.semver import SemVer


class TestVmsSessionSuite:

    @pytest.mark.parametrize("cluster_version", [
        "4.3.9", "4.0.11.12", "3.4.6.123.1", "4.5.6-1"
    ])
    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
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
                patch("vast_csi.vms_session.VmsSession.get_snapshot_stream", side_effect=raise_http_err)
        ):
            with pytest.raises(OperationNotSupported) as exc:
                cont.vms_session.ensure_snapshot_stream(snapshot_id=1, destination_path='/test',
                                                        snapshot_stream_name="test-snap", background_sync=True)

        # Assertion
        assert f"Cluster does not support this operation - 'create_globalsnapshotstream'" \
               f" (needs 4.7.0, got {stripped_version})\n    current_version = {stripped_version}\n" \
               f"    op = create_globalsnapshotstream\n    required_version = 4.7.0" in exc.value.render(color=False)

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_requisite_decorator_execution_not_ignored(self):
        """Test `requisite` decorator not ignore execution when cluster version met requirements"""
        # Preparation
        cont = Controller()
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = "4.7.0"

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
                patch("vast_csi.vms_session.VmsSession.get_snapshot_stream", side_effect=raise_http_err)
        ):
            # Assertion
            with pytest.raises(HTTPError):
                cont.vms_session.ensure_snapshot_stream_deleted(snapshot_stream_name="test-snap")

    @patch("vast_csi.configuration.Config.vms_user", PropertyMock("test"))
    @patch("vast_csi.configuration.Config.vms_password", PropertyMock("test"))
    @patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock())
    def test_requisite_decorator_execution_ignored(self):
        """Test `requisite` decorator ignores execution when cluster version doesn't met requirements"""
        # Preparation
        cont = Controller()
        fake_mgmt = MagicMock(None)
        fake_mgmt.sw_version = "4.4.0"

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
                patch("vast_csi.vms_session.VmsSession.get_snapshot_stream", side_effect=raise_http_err)
        ):
            # Assertion
            assert not cont.vms_session.ensure_snapshot_stream_deleted(snapshot_stream_name="test-snap")
