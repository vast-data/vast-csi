import re
import pytest
from unittest.mock import patch, PropertyMock, MagicMock
from vast_csi.server import CsiController, Abort, MissingParameter

import grpc
import vast_csi.csi_types as types
from easypy.bunch import Bunch


class TestControllerSuite:

    @pytest.mark.parametrize("fs_type, mount_flags, mode, err_message", [
        ("abc", "abc", types.AccessModeType.SINGLE_NODE_WRITER, "Unsupported file system type: abc"),
        ("ext4", "", types.AccessModeType.MULTI_NODE_SINGLE_WRITER, "Unsupported access mode: 4 (use [1, 2, 3, 5])"),
    ])
    def test_create_volume_invalid_capability(self, volume_capabilities, fs_type, mount_flags, mode, err_message):
        """Test invalid VolumeCapabilities must be validated"""
        # Preparation
        cont = CsiController()
        capabilities = volume_capabilities(fs_type=fs_type, mount_flags=mount_flags, mode=mode)

        # Execution
        with pytest.raises(Abort) as ex_context:
            cont.CreateVolume(None,"test_volume", capabilities)

        # Assertion
        err = ex_context.value
        assert err.message == err_message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

    @pytest.mark.parametrize("parameters, err_message", [
        (dict(view_policy="default", vip_pool_name="vippool-1"), "Parameter 'root_export' cannot be empty"),
        (dict(root_export="/k8s", vip_pool_name="vippool-1"), "Parameter 'view_policy' cannot be empty"),
    ])
    def test_validate_parameters(self, volume_capabilities, parameters, err_message):
        """Test all required parameters must be provided"""
        # Preparation
        cont = CsiController()
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)

        # Execution
        with pytest.raises(MissingParameter) as ex_context:
            cont.CreateVolume(None, name="test_volume", volume_capabilities=capabilities, parameters=parameters)

        # Assertion
        err = ex_context.value
        assert err_message in err.message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_local_ip_for_mount(self, volume_capabilities, vms_session, monkeypatch):
        # Preparation
        cont = CsiController()
        monkeypatch.setattr(vms_session.config, "use_local_ip_for_mount", "test.com")
        data = dict(root_export="/k8s", view_policy="default")
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)

        # Execution
        with pytest.raises(Abort) as ex_context:
            cont.CreateVolume(vms_session=vms_session, name="test_volume", volume_capabilities=capabilities, parameters=data)

        # Assertion
        err = ex_context.value
        assert "Local IP address: test.com is invalid" in err.message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

        # Execution
        monkeypatch.setattr(vms_session.config, "use_local_ip_for_mount", "")
        with pytest.raises(Abort) as ex_context:
            cont.CreateVolume(vms_session=vms_session, name="test_volume", volume_capabilities=capabilities, parameters=data)

        # Assertion
        err = ex_context.value
        assert "either vip_pool_name, vip_pool_fqdn or use_local_ip_for_mount" in err.message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

    def test_quota_hard_limit_not_match(self, volume_capabilities, fake_session: "FakeSession"):
        """Test quota exists but provided capacity doesnt match"""
        # Preparation
        cont = CsiController()
        parameters = dict(root_export="/foo/bar", view_policy="default", vip_pool_name="vippool-1")
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)

        # Execution
        with pytest.raises(Abort) as ex_context:
            with fake_session(quota_hard_limit=999) as session:
                cont.CreateVolume(vms_session=session, name="test_volume", volume_capabilities=capabilities, parameters=parameters)

        # Assertion
        err = ex_context.value
        assert err.message == "Volume already exists with different capacity than requested (999)"
        assert err.code == grpc.StatusCode.ALREADY_EXISTS
        assert session.ensure_view.call_count == 1
        assert session.get_quota.call_count == 1
        assert session.ensure_view.call_args.args == ()
        assert session.get_quota.call_args.args == ("test_volume",)

    @pytest.mark.parametrize("raw_mount_options", [
        "[vers=4 ,  nolock,   proto=tcp,   nconnect=4]",
        "[vers=4 nolock proto=tcp nconnect=4]",
        "[vers=4,nolock,proto=tcp,nconnect=4]",
        "vers=4 ,  nolock,   proto=tcp,   nconnect=4",
        "vers=4 nolock proto=tcp nconnect=4",
        "vers=4,nolock,proto=tcp,nconnect=4",
    ])
    def test_parse_mount_options(self, raw_mount_options):
        mount_options = ",".join(re.sub(r"[\[\]]", "", raw_mount_options).replace(",", " ").split())
        assert mount_options == "vers=4,nolock,proto=tcp,nconnect=4"

    @patch("vast_csi.vms_session.VmsSession.get_quota", MagicMock(return_value=Bunch(tenant_id=1)))
    @patch("vast_csi.vms_session.VmsSession.get_vip", MagicMock(return_value="2.2.2.2"))
    @pytest.mark.parametrize("local_ip", ["1.1.1.1", "::1", "2001:0db8:85a3:0000:0000:8a2e:0370:7334"])
    @pytest.mark.parametrize("vip_pool_name", ["", "test-vip"])
    def test_publish_volume_with_local_ip(self, vms_session, volume_capabilities, monkeypatch, local_ip, vip_pool_name):
        """
        Test if use_local_ip_for_mount is set, it will use local IP for mount (even when vip_pool_name is provided)
        """
        # Preparation
        cont = CsiController()
        conf = vms_session.config
        node_id = "test-node"
        volume_id = "test-volume"
        monkeypatch.setattr(conf, "use_local_ip_for_mount", local_ip),
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)
        volume_context = dict(root_export="/test", vip_pool_name=vip_pool_name)

        # Execution
        resp = cont.ControllerPublishVolume(
            vms_session=vms_session, node_id=node_id, volume_id=volume_id, volume_capability=capabilities[0], volume_context=volume_context
        )
        publish_context = resp.publish_context

        # Assertion
        assert publish_context["export_path"] == "/test/test-volume"
        if vip_pool_name:
            assert publish_context["nfs_server_ip"] == "2.2.2.2"
        else:
            assert publish_context["nfs_server_ip"] == local_ip
