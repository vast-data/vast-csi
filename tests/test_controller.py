import uuid
import pytest
import contextlib
from contextlib import ExitStack
from unittest.mock import MagicMock
from vast_csi.plugins.nfs import CsiController
from vast_csi.plugins.block import BlockController
from vast_csi.exceptions import Abort, MissingParameter

import grpc
import vast_csi.csi_types as types
from vast_csi.utils import wrap_ipv6
from easypy.bunch import Bunch


class TestControllerSuite:

    @pytest.mark.parametrize("fs_type, mount_flags, mode, err_message", [
        ("abc", "abc", types.AccessModeType.SINGLE_NODE_WRITER, "unsupported file system type: abc"),
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
        assert err_message in err.message
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

    def test_quota_hard_limit_not_match(self, volume_capabilities, vms_session):
        """Test quota exists but provided capacity doesnt match"""
        # Preparation
        cont = CsiController()
        parameters = dict(root_export="/foo/bar", view_policy="default", vip_pool_name="vippool-1")
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)
        vms_session.views.ensure = MagicMock()
        vms_session.quotas.one = MagicMock(return_value=Bunch(tenant_id=1, hard_limit=999))
        vms_session.viewpolicies.one = MagicMock(return_value=Bunch(
            name="default", nfs_enforce_tls=False, nfs_enforce_tls_relaxed=False, nfs_enforce_mtls=False
        ))

        # Execution
        with pytest.raises(Exception) as ex_context:
            cont.CreateVolume(
                vms_session=vms_session, name="test_volume",
                volume_capabilities=capabilities, parameters=parameters, capacity_range=Bunch(required_bytes=1000)
            )
        # Assertion
        err = ex_context.value
        assert str(err) == "Volume already exists with different capacity than requested (999)"
        assert vms_session.views.ensure.call_count == 1
        assert vms_session.quotas.one.call_count == 1
        assert vms_session.views.ensure.call_args.args == ()
        assert vms_session.quotas.one.call_args.kwargs["path"] == "/foo/bar/test_volume"

    @pytest.mark.parametrize("local_ip", ["1.1.1.1", "::1", "2001:0db8:85a3:0000:0000:8a2e:0370:7334"])
    @pytest.mark.parametrize("vip_pool_name", ["", "test-vip"])
    def test_publish_volume_with_local_ip(self, vms_session_with_mocked_resources_factory, volume_capabilities, monkeypatch, local_ip, vip_pool_name):
        """
        Test if use_local_ip_for_mount is set, it will use local IP for mount (even when vip_pool_name is provided)
        """
        # Preparation
        session = vms_session_with_mocked_resources_factory(
            ("vippools", "get_vip", "2.2.2.2"),
            ("quotas", "one", Bunch(tenant_id=1)),
        )
        cont = CsiController()
        conf = session.config
        node_id = "test-node"
        volume_id = "test-volume"
        monkeypatch.setattr(conf, "use_local_ip_for_mount", local_ip),
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)
        volume_context = dict(root_export="/test", vip_pool_name=vip_pool_name)

        # Execution
        resp = cont.ControllerPublishVolume(
            vms_session=session,
            node_id=node_id,
            volume_id=volume_id,
            volume_capability=capabilities[0],
            volume_context=volume_context
        )
        publish_context = resp.publish_context

        # Assertion
        assert publish_context["export_path"] == "/test/test-volume"
        if vip_pool_name:
            assert publish_context["nfs_server_ip"] == "2.2.2.2"
        else:
            assert publish_context["nfs_server_ip"] == wrap_ipv6(local_ip)

    def test_static_volume_no_vip_pool(self, vms_session, volume_capabilities):
        # Prepare test data
        volume_id = "/static/volume/path"
        node_id = "node1"
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)
        cont = CsiController()

        with pytest.raises(Abort) as ex_context:
            cont.ControllerPublishVolume(vms_session, node_id, volume_id, capabilities[0], {})

        err = ex_context.value
        assert "either vip_pool_name, vip_pool_fqdn or use_local_ip_for_mount must be provided." in err.message

    def test_static_volume_no_vip_policy(self, vms_session, volume_capabilities):
        # Prepare test data
        volume_id = "/static/volume/path"
        node_id = "node1"
        volume_context = dict(vip_pool_name="vippool-1", static_pv_create_views="yes")
        capabilities = volume_capabilities(fs_type="ext4", mount_flags="", mode=types.AccessModeType.SINGLE_NODE_WRITER)
        cont = CsiController()

        with pytest.raises(Abort) as ex_context:
            cont.ControllerPublishVolume(vms_session, node_id, volume_id, capabilities[0], volume_context)

        err = ex_context.value
        assert "Parameter 'view_policy' cannot be empty string or None" in err.message

    @pytest.mark.parametrize("kwargs", [
        dict(static_pv_create_views="yes"),
        dict(static_pv_create_quotas="yes"),
        dict(static_pv_create_view="yes", static_pv_create_quotas="yes"),
    ])
    def test_static_volume_create_create_view_and_quota(
            self, vms_session_with_mocked_resources_factory, volume_capabilities, kwargs
    ):
        # Prepare test data
        volume_id = "/static/volume/path/"
        node_id = "node1"
        volume_context = dict(vip_pool_name="vippool-1", view_policy="default", **kwargs)
        capabilities = volume_capabilities(
            fs_type="ext4", mount_flags=["test"], mode=types.AccessModeType.SINGLE_NODE_WRITER
        )
        view = Bunch(path="/test/view", id=1, tenant_id=1, tenant_name="default")
        quota = Bunch(id=1, hard_limit=1000, tenant_id=1, tenant_name="test")
        viewpolicy = Bunch(name="default", nfs_enforce_tls=False, nfs_enforce_tls_relaxed=False, nfs_enforce_mtls=False)
        cont = CsiController()
        session = vms_session_with_mocked_resources_factory(
            ("views", "one", view),
            ("views", "ensure", view),
            ("quotas", "one", quota),
            ("quotas", "ensure", quota),
            ("vippools", "get_vip", "127.0.0.1"),
            ("viewpolicies", "one", viewpolicy),
        )
        resp = cont.ControllerPublishVolume(session, node_id, volume_id, capabilities[0], volume_context)

        publish_context = dict(resp.publish_context)
        assert publish_context["nfs_server_ip"] == "127.0.0.1"
        assert publish_context["export_path"] == volume_id.rstrip("/")
        assert publish_context["mount_options"] == "test"

        if kwargs.get("static_pv_create_views"):
            session.views.ensure.assert_called_once_with(
                path=volume_id.rstrip("/"),
                protocols=['NFS'],
                view_policy='default',
                qos_policy=None,
                qos_policy_id=None,
            )
        else:
            session.views.ensure.assert_not_called()
        if kwargs.get("static_pv_create_quotas"):
            session.quotas.ensure.assert_called_once_with(
                volume_id="csi-" + str(uuid.uuid5(uuid.NAMESPACE_DNS, volume_id.rstrip("/"))),
                view_path=volume_id.rstrip("/"), tenant_id=1,  requested_capacity=0,
            )
        else:
            session.quotas.ensure.assert_not_called()

    def test_static_volume_wrong_tenant(self, vms_session_with_mocked_resources_factory, volume_capabilities):
        # Prepare test data
        volume_id = "/static/volume/path/"
        node_id = "node1"
        volume_context = dict(vip_pool_name="vippool-1", view_policy="default", static_pv_create_quotas="yes")
        capabilities = volume_capabilities(
            fs_type="ext4", mount_flags=["test"], mode=types.AccessModeType.SINGLE_NODE_WRITER
        )
        viewpolicy = Bunch(name="default", nfs_enforce_tls=False, nfs_enforce_tls_relaxed=False, nfs_enforce_mtls=False)
        session = vms_session_with_mocked_resources_factory(
            ("views", "one", Bunch(path=volume_id, id=1, tenant_id=5, tenant_name="default")),
            ("quotas", "one", Bunch(tenant_id=1, hard_limit=999, tenant_name="test")),
            ("vippools", "get_vip", "127.0.0.1"),
            ("viewpolicies", "one", viewpolicy),
        )
        cont = CsiController()
        with pytest.raises(Exception) as ex_context:
            cont.ControllerPublishVolume(session, node_id, volume_id, capabilities[0], volume_context)

        err = ex_context.value
        assert "Volume already exists with different tenancy ownership (test)" in str(err)


class TestBlockControllerCleanup:

    @pytest.fixture()
    def vms_session_mock(self):
        session = Bunch()
        session.volumes = Bunch()
        session.blockhostmappings = Bunch()
        session.blockhosts = Bunch()

        # Defaults; individual tests will override as needed
        session.volumes.one = MagicMock(return_value=Bunch(id=1, tenant_name="tenant-a"))
        session.blockhostmappings.ensure_unmap = MagicMock()
        session.blockhosts.one = MagicMock(return_value=Bunch(id=2, mapped_volumes_preview=[], nqn="nqn.2014-08.com.vastcsiblock:default:node-1"))
        session.blockhosts.delete_by_id = MagicMock()
        return session

    @pytest.fixture()
    def no_op_volume_lock(self, monkeypatch):
        calls = []

        @contextlib.contextmanager
        def _fake_volume_locked(key):
            calls.append(key)
            yield

        monkeypatch.setattr("vast_csi.plugins.block.resource_locked", _fake_volume_locked)
        return calls

    @pytest.fixture()
    def conf_with_prefix(self, monkeypatch):
        # Enable auto prune for tests that assert deletion
        monkeypatch.setattr(
            "vast_csi.plugins.block.CONF",
            Bunch(block_nqn_prefix="nqn.2014-08.com.vastcsiblock", block_hosts_auto_prune=True, block_hosts_prefix=""),
        )

    def test_unpublish_deletes_host_when_last_volume(self, vms_session_mock, no_op_volume_lock, conf_with_prefix):
        controller = BlockController()
        node_id = "node-1"
        volume_id = "vol-1"

        resp = controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id=node_id,
            volume_id=volume_id,
            exit_stack=ExitStack(),
        )

        from vast_csi import csi_types as types
        assert isinstance(resp, types.CtrlUnpublishResp)
        vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once_with(
            volume__id=1, block_host__name=node_id
        )
        vms_session_mock.blockhosts.delete_by_id.assert_called_once_with(2)
        # lock taken with composite key
        assert no_op_volume_lock == [f"{node_id}:tenant-a"]

    def test_unpublish_does_not_delete_host_when_mappings_exist(self, vms_session_mock, no_op_volume_lock):
        vms_session_mock.blockhosts.one = MagicMock(
            return_value=Bunch(id=2, mapped_volumes_preview=[{"id": 1}])
        )
        controller = BlockController()

        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="vol-1",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once()
        vms_session_mock.blockhosts.delete_by_id.assert_not_called()

    def test_unpublish_volume_not_found_skips_unmap_and_delete(self, vms_session_mock, no_op_volume_lock):
        vms_session_mock.volumes.one = MagicMock(return_value=None)
        controller = BlockController()

        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="missing-vol",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhostmappings.ensure_unmap.assert_not_called()
        vms_session_mock.blockhosts.delete_by_id.assert_not_called()

    def test_unpublish_host_not_found_no_delete(self, vms_session_mock, no_op_volume_lock):
        vms_session_mock.blockhosts.one = MagicMock(return_value=None)
        controller = BlockController()

        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="vol-1",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhostmappings.ensure_unmap.assert_called_once()
        vms_session_mock.blockhosts.delete_by_id.assert_not_called()

    def test_unpublish_deletes_only_when_host_nqn_has_driver_prefix(self, vms_session_mock, no_op_volume_lock, monkeypatch):
        # Host with matching NQN prefix should be deleted when last volume is unmapped
        monkeypatch.setattr(
            "vast_csi.plugins.block.CONF",
            Bunch(block_nqn_prefix="nqn.2014-08.com.vastcsiblock", block_hosts_auto_prune=True, block_hosts_prefix=""),
        )
        vms_session_mock.blockhosts.one = MagicMock(return_value=Bunch(id=2, mapped_volumes_preview=[], nqn="nqn.2014-08.com.vastcsiblock:default:node-1"))

        controller = BlockController()
        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="vol-1",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhosts.delete_by_id.assert_called_once_with(2)

    def test_unpublish_does_not_delete_when_host_nqn_without_driver_prefix(self, vms_session_mock, no_op_volume_lock, monkeypatch):
        # Host with non-matching NQN prefix should NOT be deleted even if last volume
        monkeypatch.setattr(
            "vast_csi.plugins.block.CONF",
            Bunch(block_nqn_prefix="nqn.2014-08.com.vastcsiblock", block_hosts_auto_prune=True, block_hosts_prefix=""),
        )
        vms_session_mock.blockhosts.one = MagicMock(return_value=Bunch(id=2, mapped_volumes_preview=[], nqn="nqn.2014-08.com.otherstack:default:node-1"))

        controller = BlockController()
        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="vol-1",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhosts.delete_by_id.assert_not_called()

    def test_unpublish_does_not_delete_when_auto_prune_disabled(self, vms_session_mock, no_op_volume_lock, monkeypatch):
        # Even with matching prefix and last volume, do not delete if auto prune is disabled
        monkeypatch.setattr(
            "vast_csi.plugins.block.CONF",
            Bunch(block_nqn_prefix="nqn.2014-08.com.vastcsiblock", block_hosts_auto_prune=False, block_hosts_prefix=""),
        )
        vms_session_mock.blockhosts.one = MagicMock(return_value=Bunch(id=2, mapped_volumes_preview=[], nqn="nqn.2014-08.com.vastcsiblock:default:node-1"))

        controller = BlockController()
        controller.ControllerUnpublishVolume(
            vms_session=vms_session_mock,
            node_id="node-1",
            volume_id="vol-1",
            exit_stack=ExitStack(),
        )

        vms_session_mock.blockhosts.delete_by_id.assert_not_called()
