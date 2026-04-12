"""
Tests for ReplicationSource helper class and ReplicationRole enum.
"""
import pytest
from unittest.mock import MagicMock
from vast_csi.plugins.replication import ReplicationSource
from vast_csi.plugins.replication import ReplicationRole
from vast_csi.exceptions import Abort


def _make_nfs_controller():
    """Return a mock controller that behaves like NFSReplicationController."""
    controller = MagicMock()
    # Mirrors NFSReplicationController._list_volumes_in_group: resolves the ppath
    # by name then lists views under its source_dir.
    def _list_volumes_in_group(vms_session, parsed):
        ppath = vms_session.protectedpaths.one(name=parsed.ppath_name, fail_if_missing=True)
        return vms_session.views.list(path__startswith=ppath.source_dir)
    controller._list_volumes_in_group.side_effect = _list_volumes_in_group
    controller._get_volume_id.side_effect = lambda vol: vol["path"].rsplit("/", 1)[-1]
    return controller


class TestReplicationSource:
    """Test suite for ReplicationSource class."""

    def test_volume_source(self):
        """Test single volume replication source."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: field == 'volume'
        mock_source.volume.volume_id = "test-volume-123"

        source = ReplicationSource(mock_source, vms_session=MagicMock(), controller=MagicMock())

        assert source.is_volume is True
        assert source.is_volume_group is False
        assert source.volume_id == "test-volume-123"
        assert source.volume_ids == ["test-volume-123"]

    def test_volume_group_source(self):
        """Test volume group replication source."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: field == 'volumegroup'
        # New format: {suffix}@n={ppath_name}
        mock_source.volumegroup.volume_group_id = "vg-456@n=app-replication"

        mock_ppath = MagicMock()
        mock_ppath.source_dir = "/k8s"

        mock_vms_session = MagicMock()
        mock_vms_session.protectedpaths.one.return_value = mock_ppath
        mock_vms_session.views.list.return_value = [
            {"path": "/k8s/vol1"},
            {"path": "/k8s/vol2"},
        ]

        source = ReplicationSource(
            mock_source, vms_session=mock_vms_session, controller=_make_nfs_controller()
        )

        assert source.is_volume is False
        assert source.is_volume_group is True
        assert source.volume_group_id == "vg-456"
        assert source.volume_ids == ["vol1", "vol2"]
        mock_vms_session.protectedpaths.one.assert_called_once_with(
            name="app-replication", fail_if_missing=True
        )

    def test_none_source_raises(self):
        """Test that None source raises Abort."""
        with pytest.raises(Abort) as exc_info:
            ReplicationSource(None, vms_session=MagicMock(), controller=MagicMock())

        assert "replication_source must be specified" in str(exc_info.value)

    def test_invalid_source_raises(self):
        """Test that source without volume or volumegroup raises Abort."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: False

        with pytest.raises(Abort) as exc_info:
            ReplicationSource(mock_source, vms_session=MagicMock(), controller=MagicMock())

        assert "must specify either volume or volumegroup" in str(exc_info.value)

    def test_volume_id_on_volume_group_raises(self):
        """Test that accessing volume_id on volumegroup source raises."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: field == 'volumegroup'
        mock_source.volumegroup.volume_group_id = "test-vg-456@n=app-replication"

        source = ReplicationSource(
            mock_source, vms_session=MagicMock(), controller=MagicMock()
        )

        with pytest.raises(Abort) as exc_info:
            _ = source.volume_id

        assert "Cannot get volume_id from volume group source" in str(exc_info.value)

    def test_volume_group_id_on_volume_raises(self):
        """Test that accessing volume_group_id on volume source raises."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: field == 'volume'
        mock_source.volume.volume_id = "test-volume-123"

        source = ReplicationSource(
            mock_source, vms_session=MagicMock(), controller=MagicMock()
        )

        with pytest.raises(Abort) as exc_info:
            _ = source.volume_group_id

        assert "Cannot get volume_group_id from single volume source" in str(exc_info.value)

    def test_cached_properties(self):
        """Test that properties are cached."""
        mock_source = MagicMock()
        mock_source.HasField = lambda field: field == 'volume'
        mock_source.volume.volume_id = "test-volume-123"

        source = ReplicationSource(
            mock_source, vms_session=MagicMock(), controller=MagicMock()
        )

        # Access multiple times - should use cached values
        assert source.is_volume is True
        assert source.is_volume is True  # Second access uses cache
        assert source.volume_ids == ["test-volume-123"]
        assert source.volume_ids == ["test-volume-123"]  # Cached


class TestReplicationRole:
    """Test suite for ReplicationRole enum."""

    def test_enum_values(self):
        """Test ReplicationRole enum has correct values."""
        # Stable states
        assert ReplicationRole.SOURCE.value == "SOURCE"
        assert ReplicationRole.DESTINATION.value == "DESTINATION"
        assert ReplicationRole.STANDALONE.value == "STANDALONE"
        assert ReplicationRole.INVALID.value == "INVALID"
        
        # Special values
        assert ReplicationRole.NA.value == "N/A"
        
        # Transitional states
        assert ReplicationRole.BECOMING_STANDALONE.value == "BECOMING_STANDALONE"
        assert ReplicationRole.BECOMING_DESTINATION.value == "BECOMING_DESTINATION"
        assert ReplicationRole.BECOMING_SOURCE_ASK_FOR_SOURCE.value == "BECOMING_SOURCE_ASK_FOR_SOURCE"
        assert ReplicationRole.BECOMING_SOURCE_ATTACHING_MEMBERS.value == "BECOMING_SOURCE_ATTACHING_MEMBERS"
        assert ReplicationRole.BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS.value == "BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS"
        assert ReplicationRole.BECOMING_SOURCE_GRACEFULLY_FAILING_OVER.value == "BECOMING_SOURCE_GRACEFULLY_FAILING_OVER"
        
        # Fallback
        assert ReplicationRole.UNKNOWN.value == "UNKNOWN"

    def test_from_string_uppercase(self):
        """Test from_string with uppercase input."""
        role = ReplicationRole.from_string("SOURCE")
        assert role == ReplicationRole.SOURCE
        
        role = ReplicationRole.from_string("DESTINATION")
        assert role == ReplicationRole.DESTINATION

    def test_from_string_lowercase(self):
        """Test from_string with lowercase input (should convert to uppercase)."""
        role = ReplicationRole.from_string("source")
        assert role == ReplicationRole.SOURCE
        
        role = ReplicationRole.from_string("destination")
        assert role == ReplicationRole.DESTINATION

    def test_from_string_mixed_case(self):
        """Test from_string with mixed case input."""
        role = ReplicationRole.from_string("Source")
        assert role == ReplicationRole.SOURCE
        
        role = ReplicationRole.from_string("DeStInAtIoN")
        assert role == ReplicationRole.DESTINATION

    def test_from_string_none(self):
        """Test from_string with None input returns UNKNOWN."""
        role = ReplicationRole.from_string(None)
        assert role == ReplicationRole.UNKNOWN

    def test_from_string_empty_string(self):
        """Test from_string with empty string returns UNKNOWN."""
        role = ReplicationRole.from_string("")
        assert role == ReplicationRole.UNKNOWN

    def test_from_string_standalone(self):
        """Test from_string with STANDALONE role."""
        role = ReplicationRole.from_string("STANDALONE")
        assert role == ReplicationRole.STANDALONE
        
        role = ReplicationRole.from_string("standalone")
        assert role == ReplicationRole.STANDALONE

    def test_from_string_invalid(self):
        """Test from_string with INVALID role."""
        role = ReplicationRole.from_string("INVALID")
        assert role == ReplicationRole.INVALID
        
        role = ReplicationRole.from_string("invalid")
        assert role == ReplicationRole.INVALID

    def test_from_string_na(self):
        """Test from_string with N/A role."""
        role = ReplicationRole.from_string("N/A")
        assert role == ReplicationRole.NA
        
        role = ReplicationRole.from_string("n/a")
        assert role == ReplicationRole.NA

    def test_from_string_transitional_states(self):
        """Test from_string with all transitional (BECOMING_*) roles."""
        # Test all BECOMING_* states
        role = ReplicationRole.from_string("BECOMING_STANDALONE")
        assert role == ReplicationRole.BECOMING_STANDALONE
        
        role = ReplicationRole.from_string("becoming_destination")
        assert role == ReplicationRole.BECOMING_DESTINATION
        
        role = ReplicationRole.from_string("BECOMING_SOURCE_ASK_FOR_SOURCE")
        assert role == ReplicationRole.BECOMING_SOURCE_ASK_FOR_SOURCE
        
        role = ReplicationRole.from_string("becoming_source_attaching_members")
        assert role == ReplicationRole.BECOMING_SOURCE_ATTACHING_MEMBERS
        
        role = ReplicationRole.from_string("BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS")
        assert role == ReplicationRole.BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS
        
        role = ReplicationRole.from_string("becoming_source_gracefully_failing_over")
        assert role == ReplicationRole.BECOMING_SOURCE_GRACEFULLY_FAILING_OVER

    def test_from_string_truly_invalid_returns_unknown(self):
        """Test from_string with truly invalid/unknown input returns UNKNOWN."""
        # Only unknown roles should return UNKNOWN
        role = ReplicationRole.from_string("PRIMARY")
        assert role == ReplicationRole.UNKNOWN
        
        role = ReplicationRole.from_string("SECONDARY")
        assert role == ReplicationRole.UNKNOWN
        
        role = ReplicationRole.from_string("SOME_FUTURE_ROLE")
        assert role == ReplicationRole.UNKNOWN

    def test_from_string_with_whitespace(self):
        """Test from_string handles strings with whitespace correctly."""
        # Note: current implementation doesn't strip whitespace
        # so " SOURCE " returns UNKNOWN - this test documents that behavior
        role = ReplicationRole.from_string(" SOURCE ")
        assert role == ReplicationRole.UNKNOWN
        
        role = ReplicationRole.from_string("SOURCE ")
        assert role == ReplicationRole.UNKNOWN

    def test_role_comparison(self):
        """Test that roles can be compared."""
        source1 = ReplicationRole.from_string("source")
        source2 = ReplicationRole.from_string("SOURCE")
        destination = ReplicationRole.from_string("destination")
        
        assert source1 == source2
        assert source1 == ReplicationRole.SOURCE
        assert destination == ReplicationRole.DESTINATION
        assert source1 != destination

    def test_role_as_string(self):
        """Test that roles can be used as strings."""
        role = ReplicationRole.from_string("source")
        
        # StrEnum allows direct string comparison
        assert role == "SOURCE"
        assert str(role) == "SOURCE"
        assert role.value == "SOURCE"

    def test_is_transitional(self):
        """Test is_transitional() method."""
        # Stable states should not be transitional
        assert not ReplicationRole.SOURCE.is_transitional()
        assert not ReplicationRole.DESTINATION.is_transitional()
        assert not ReplicationRole.STANDALONE.is_transitional()
        assert not ReplicationRole.INVALID.is_transitional()
        assert not ReplicationRole.NA.is_transitional()
        assert not ReplicationRole.UNKNOWN.is_transitional()
        
        # All BECOMING_* states should be transitional
        assert ReplicationRole.BECOMING_STANDALONE.is_transitional()
        assert ReplicationRole.BECOMING_DESTINATION.is_transitional()
        assert ReplicationRole.BECOMING_SOURCE_ASK_FOR_SOURCE.is_transitional()
        assert ReplicationRole.BECOMING_SOURCE_ATTACHING_MEMBERS.is_transitional()
        assert ReplicationRole.BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS.is_transitional()
        assert ReplicationRole.BECOMING_SOURCE_GRACEFULLY_FAILING_OVER.is_transitional()

    def test_is_stable(self):
        """Test is_stable() method."""
        # Stable states
        assert ReplicationRole.SOURCE.is_stable()
        assert ReplicationRole.DESTINATION.is_stable()
        assert ReplicationRole.STANDALONE.is_stable()
        
        # Non-stable states
        assert not ReplicationRole.INVALID.is_stable()
        assert not ReplicationRole.NA.is_stable()
        assert not ReplicationRole.UNKNOWN.is_stable()
        assert not ReplicationRole.BECOMING_STANDALONE.is_stable()
        assert not ReplicationRole.BECOMING_DESTINATION.is_stable()
        assert not ReplicationRole.BECOMING_SOURCE_ASK_FOR_SOURCE.is_stable()
        assert not ReplicationRole.BECOMING_SOURCE_ATTACHING_MEMBERS.is_stable()
        assert not ReplicationRole.BECOMING_SOURCE_FAILING_OVER_STANDBY_PEERS.is_stable()
        assert not ReplicationRole.BECOMING_SOURCE_GRACEFULLY_FAILING_OVER.is_stable()
