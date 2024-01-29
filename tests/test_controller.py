import re
import pytest
from vast_csi.server import CsiController, Abort, MissingParameter

import grpc
import vast_csi.csi_types as types


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
            cont.CreateVolume("test_volume", capabilities)

        # Assertion
        err = ex_context.value
        assert err.message == err_message
        assert err.code == grpc.StatusCode.INVALID_ARGUMENT

    @pytest.mark.parametrize("parameters, err_message", [
        (dict(view_policy="default", vip_pool_name="vippool-1"), "Parameter 'root_export' cannot be empty"),
        (dict(root_export="/k8s", vip_pool_name="vippool-1"), "Parameter 'view_policy' cannot be empty"),
        (dict(root_export="/k8s", view_policy="default"), "Parameter 'vip_pool_name' cannot be empty"),
    ])
    def test_validate_parameters(self, volume_capabilities, parameters, err_message):
        """Test all required parameters must be provided"""
        # Preparation
        cont = CsiController()
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)

        # Execution
        with pytest.raises(MissingParameter) as ex_context:
            cont.CreateVolume(name="test_volume", volume_capabilities=capabilities, parameters=parameters)

        # Assertion
        err = ex_context.value
        assert err_message in err.message
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
                cont.CreateVolume(name="test_volume", volume_capabilities=capabilities, parameters=parameters)

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
