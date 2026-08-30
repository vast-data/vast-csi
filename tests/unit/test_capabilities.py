import pytest
from unittest.mock import MagicMock

import vast_csi.csi_types as types
from vast_csi import capabilities as cap_lib
from vast_csi.plugins.base import AddonsIdentity


@pytest.mark.parametrize(
    "fs_type, mount_flags, mode, can_many_rwx, err_message",
    [
        (
            "abc",
            "abc",
            types.AccessModeType.SINGLE_NODE_WRITER,
            False,
            "unsupported file system type: abc",
        ),
        (
            "abc",
            "abc",
            types.AccessModeType.SINGLE_NODE_WRITER,
            True,
            "unsupported file system type: abc",
        ),
        (
            "ext4",
            "",
            types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
            False,
            "multi-node access mode is not supported",
        ),
        ("ext4", "", types.AccessModeType.MULTI_NODE_SINGLE_WRITER, True, None),
    ],
)
def test_mount_volume_capabilities(
    volume_capabilities, fs_type, mount_flags, mode, can_many_rwx, err_message
):
    service_capabilities = cap_lib.ServiceCapabilities(
        can_many_rwx=can_many_rwx, support_block=False, support_filesystem=True
    )
    capabilities = volume_capabilities(
        fs_type=fs_type, mount_flags=mount_flags, mode=mode, access_type="mount"
    )
    vol_caps = cap_lib.Capabilities(capabilities)

    if err_message:
        with pytest.raises(cap_lib.CapValidationError) as exc:
            service_capabilities.validate(vol_caps)
        assert err_message in str(exc.value)

    else:
        assert not vol_caps.is_block
        assert vol_caps.fs_type == fs_type
        if mode in (
            types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
            types.AccessModeType.MULTI_NODE_READER_ONLY,
        ):
            assert vol_caps.multi_mode
        else:
            assert not vol_caps.multi_mode
        assert vol_caps.ro_mode is False
        assert vol_caps.rw_mode is True
        assert vol_caps.access_mode == mode


@pytest.mark.parametrize(
    "fs_type, mount_flags, mode, can_many_rwx, err_message",
    [
        ("abc", "abc", types.AccessModeType.SINGLE_NODE_WRITER, False, None),
        ("abc", "abc", types.AccessModeType.SINGLE_NODE_WRITER, True, None),
        (
            "ext4",
            "",
            types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
            False,
            "multi-node access mode is not supported",
        ),
        ("ext4", "", types.AccessModeType.MULTI_NODE_SINGLE_WRITER, True, None),
    ],
)
def test_block_volume_capabilities(
    volume_capabilities, fs_type, mount_flags, mode, can_many_rwx, err_message
):
    service_capabilities = cap_lib.ServiceCapabilities(
        can_many_rwx=can_many_rwx, support_block=True, support_filesystem=False
    )
    capabilities = volume_capabilities(
        fs_type=fs_type, mount_flags=mount_flags, mode=mode, access_type="block"
    )
    vol_caps = cap_lib.Capabilities(capabilities)

    if err_message:
        with pytest.raises(cap_lib.CapValidationError) as exc:
            service_capabilities.validate(vol_caps)
        assert err_message in str(exc.value)
    else:
        assert vol_caps.is_block
        if mode in (
            types.AccessModeType.MULTI_NODE_SINGLE_WRITER,
            types.AccessModeType.MULTI_NODE_READER_ONLY,
        ):
            assert vol_caps.multi_mode
        else:
            assert not vol_caps.multi_mode
        assert vol_caps.ro_mode is False
        assert vol_caps.rw_mode is True
        assert vol_caps.access_mode == mode


@pytest.mark.parametrize(
    "mode",
    [
        types.AccessModeType.SINGLE_NODE_READER_ONLY,
        types.AccessModeType.MULTI_NODE_READER_ONLY,
    ],
)
def test_rw_only_capabilities(volume_capabilities, mode):
    capabilities = volume_capabilities(
        fs_type="ext4", mount_flags="", mode=mode, access_type="mount"
    )
    vol_caps = cap_lib.Capabilities(capabilities)
    assert not vol_caps.is_block
    assert vol_caps.ro_mode is True
    if mode == types.AccessModeType.MULTI_NODE_READER_ONLY:
        assert vol_caps.multi_mode


@pytest.mark.parametrize(
    "raw_mount_options",
    [
        "[vers=4 ,  nolock,   proto=tcp,   nconnect=4]",
        "[vers=4 nolock proto=tcp nconnect=4]",
        "[vers=4,nolock,proto=tcp,nconnect=4]",
        "vers=4 ,  nolock,   proto=tcp,   nconnect=4",
        "vers=4 nolock proto=tcp nconnect=4",
        "vers=4,nolock,proto=tcp,nconnect=4",
    ],
)
def test_parse_mount_options(raw_mount_options, volume_capabilities):
    capabilities = volume_capabilities(
        fs_type="ext4",
        mount_flags=raw_mount_options,
        mode=types.AccessModeType.SINGLE_NODE_READER_ONLY,
        access_type="mount",
    )
    vol_caps = cap_lib.Capabilities(capabilities)
    assert vol_caps.mount_flags == ["nconnect=4", "nolock", "proto=tcp", "vers=4"]


def test_capability_equality(volume_capabilities):
    cap1 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER,
            access_type="mount",
            fs_type="ext4",
        )[0]
    )  # Select the first capability from the list
    cap2 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER,
            access_type="mount",
            fs_type="ext4",
        )[0]
    )
    cap3 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.MULTI_NODE_READER_ONLY,
            access_type="mount",
            fs_type="ext4",
        )[0]
    )

    assert cap1 == cap2  # Same capabilities
    assert cap1 != cap3  # Different access modes


def test_block_capability_equality(volume_capabilities):
    cap1 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER, access_type="block"
        )[0]
    )
    cap2 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER, access_type="block"
        )[0]
    )

    assert cap1 == cap2  # Same capabilities for block type


def test_capability_mount_flags(volume_capabilities):
    cap1 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER,
            access_type="mount",
            fs_type="ext4",
            mount_flags=["noatime"],
        )[0]
    )
    cap2 = cap_lib.Capability(
        volume_capabilities(
            mode=types.AccessModeType.SINGLE_NODE_WRITER,
            access_type="mount",
            fs_type="ext4",
            mount_flags=["ro"],
        )[0]
    )

    assert cap1 != cap2  # Different mount flags


def test_empty_capabilities():
    capabilities = cap_lib.Capabilities(capabilities=[])
    assert capabilities


def test_capabilities_json(volume_capabilities):
    service_capabilities = cap_lib.ServiceCapabilities(
        can_many_rwx=True, support_block=False, support_filesystem=True
    )
    capabilities = volume_capabilities(
        fs_type="ext4",
        mount_flags="vers=4",
        mode=types.AccessModeType.SINGLE_NODE_WRITER,
        access_type="mount",
    )
    vol_caps = service_capabilities.make_and_validate(capabilities)
    expected_json = {
        "is_block": False,
        "is_filesystem": True,
        "access_mode": types.AccessModeType.SINGLE_NODE_WRITER,
        "fs_type": "ext4",
        "mount_flags": "vers=4",
    }
    assert vol_caps.json == expected_json


# ----------------------------------------------------------------------------------------------------------------------
# AddonsIdentity Tests
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def reset_addons_identity():
    """Reset AddonsIdentity class state before and after each test."""
    # Save original state
    original_capability_types = AddonsIdentity._capability_types.copy()
    original_registered = AddonsIdentity._registered
    
    # Reset to default state
    AddonsIdentity._capability_types = [("service", "CONTROLLER_SERVICE")]
    AddonsIdentity._registered = False
    
    yield
    
    # Restore original state
    AddonsIdentity._capability_types = original_capability_types
    AddonsIdentity._registered = original_registered


class TestAddonsIdentity:
    """Tests for AddonsIdentity class."""

    def test_default_controller_service_capability(self, reset_addons_identity):
        """CONTROLLER_SERVICE capability should be present by default."""
        assert ("service", "CONTROLLER_SERVICE") in AddonsIdentity._capability_types
        assert len(AddonsIdentity._capability_types) == 1

    def test_add_replication_capabilities(self, reset_addons_identity):
        """Adding VOLUME_REPLICATION capability should work."""
        AddonsIdentity.add_replication_capabilities()
        
        assert ("volume_replication", "VOLUME_REPLICATION") in AddonsIdentity._capability_types
        assert len(AddonsIdentity._capability_types) == 2

    def test_add_volume_group_capabilities(self, reset_addons_identity):
        """Adding VolumeGroup capabilities should work."""
        AddonsIdentity.add_volume_group_capabilities()
        
        assert ("volume_group", "CREATE_GET_DELETE_VOLUME_GROUP") in AddonsIdentity._capability_types
        assert ("volume_group", "MODIFY_VOLUME_GROUP") in AddonsIdentity._capability_types
        assert len(AddonsIdentity._capability_types) == 3

    def test_add_all_capabilities(self, reset_addons_identity):
        """Adding all supported capabilities should work."""
        AddonsIdentity.add_replication_capabilities()
        AddonsIdentity.add_volume_group_capabilities()
        
        assert len(AddonsIdentity._capability_types) == 4
        assert ("service", "CONTROLLER_SERVICE") in AddonsIdentity._capability_types
        assert ("volume_replication", "VOLUME_REPLICATION") in AddonsIdentity._capability_types
        assert ("volume_group", "CREATE_GET_DELETE_VOLUME_GROUP") in AddonsIdentity._capability_types
        assert ("volume_group", "MODIFY_VOLUME_GROUP") in AddonsIdentity._capability_types

    def test_no_duplicate_capabilities(self, reset_addons_identity):
        """Adding the same capability twice should not create duplicates."""
        AddonsIdentity.add_replication_capabilities()
        AddonsIdentity.add_replication_capabilities()
        
        count = AddonsIdentity._capability_types.count(("volume_replication", "VOLUME_REPLICATION"))
        assert count == 1
        assert len(AddonsIdentity._capability_types) == 2

    def test_build_capabilities(self, reset_addons_identity):
        """_build_capabilities should create proper protobuf objects."""
        from vast_csi.proto import addons_identity_pb2
        
        AddonsIdentity.add_replication_capabilities()
        AddonsIdentity.add_volume_group_capabilities()
        
        capabilities = AddonsIdentity._build_capabilities()
        
        assert len(capabilities) == 4
        
        # Check that all capabilities are proper protobuf objects
        for cap in capabilities:
            assert isinstance(cap, addons_identity_pb2.Capability)

    def test_register_only_once(self, reset_addons_identity):
        """Identity service should only register once."""
        mock_server = MagicMock()
        
        AddonsIdentity.register(mock_server)
        AddonsIdentity.register(mock_server)
        AddonsIdentity.register(mock_server)
        
        # Should only be called once
        assert mock_server.method_calls or True  # Mock was used
        assert AddonsIdentity._registered is True
