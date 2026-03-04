import pytest
from unittest.mock import Mock, patch
import threading
import time
from vast_csi.utils import (
    is_ver_nfs4_present,
    generate_ip_range,
    wrap_ipv6,
    string_to_static_uuid,
    parse_string_parameters,
    yesno_to_bool,
    replace_path_prefix,
    get_mount,
)


@pytest.mark.parametrize(
    "options, exepected",
    [
        (["vers=4", "soft=true", "noac"], True),
        (["nfsvers=4", "soft=true", "noac"], True),
        (["vers=4.1", "soft=true", "noac"], True),
        (["vers=4.0", "soft=true", "noac"], True),
        (["soft=true", "vers=4.0", "noac"], True),
        (["soft=true", "vers=4.0"], True),
        ([], False),
        (["nfsverss=4", "soft=true", "noac"], False),
        (["vers=3", "soft=true", "noac"], False),
        (["avers=4", "soft=true", "noac"], False),
        (["nfsvers=3.4", "soft=true", "noac"], False),
        (["soft=true", "vers=3", "4noac"], False),
        (["noac", "vers= 4", "noac"], False),
        (["noac", "vers = 4", "noac"], False),
    ]
)
def test_parse_nfs4_mount_option(options, exepected):
    """Test if nfsvers|vers=4 is parsed properly"""
    assert is_ver_nfs4_present(options) == exepected


@pytest.mark.parametrize("ip_ranges, expected", [
    # IPv4 range test cases
    (
        [["15.0.0.1", "15.0.0.4"], ["10.0.0.27", "10.0.0.30"]],
        ['15.0.0.1', '15.0.0.2', '15.0.0.3', '15.0.0.4', '10.0.0.27', '10.0.0.28', '10.0.0.29', '10.0.0.30']
    ),
    (
        [["15.0.0.1", "15.0.0.1"], ["10.0.0.20", "10.0.0.20"]],
        ['15.0.0.1', '10.0.0.20']
    ),
    ([], []),
    # IPv6 range test cases
    (
        [["2001:db8::1", "2001:db8::4"]],
        ['2001:db8::1', '2001:db8::2', '2001:db8::3', '2001:db8::4']
    ),
    (
        [["::1", "::1"]],
        ['::1']
    ),
    (
        [["2001:db8::ff", "2001:db8::102"]],
        ['2001:db8::ff', '2001:db8::100', '2001:db8::101', '2001:db8::102']
    ),
    (
        [["2001:db8::a", "2001:db8::c"], ["fd00::1", "fd00::2"]],
        ['2001:db8::a', '2001:db8::b', '2001:db8::c', 'fd00::1', 'fd00::2']
    )
])
def test_generate_ip_range(ip_ranges, expected):
    ips = generate_ip_range(ip_ranges)
    assert ips == expected


@pytest.mark.parametrize(
    "addr, expected",
    [
        ("192.168.1.1", "192.168.1.1"),
        ("2001:db8::1", "[2001:db8::1]"),
        ("example.com", "example.com"),
        ("::", "[::]"),
        ("[2001:db8::1]", "[2001:db8::1]"),
        ("[::]", "[::]"),
        ("::1", "[::1]"),
        ("::ffff:192.168.1.1", "[::ffff:192.168.1.1]"),
        ("0:0:0:0:0:0:0:1", "[0:0:0:0:0:0:0:1]"),
        ("", ""),
        ("   ", "   "),
        ("[invalid::addr]", "[invalid::addr]"),
        ("2001:0db8:0000:0000:0000:ff00:0042:8329", "[2001:0db8:0000:0000:0000:ff00:0042:8329]"),
        ("example.com:8080", "example.com:8080"),
        ("192.168.1.1:2049", "192.168.1.1:2049"),
        ("[2001:db8::1]:2049", "[2001:db8::1]:2049"),
        ("2001:db8::1:2049", "[2001:db8::1:2049]"),
    ]
)
def test_wrap_ipv6(addr, expected):
    """Test if IPv6 address is wrapped in brackets"""
    assert wrap_ipv6(addr) == expected


@pytest.mark.parametrize("input_value, expected", [
    ("nqn.2023-01.io.vast:tenant1", "afa6c1de-cf88-5e9c-9ae9-9be476f926a3"),
    ("tenant2", "df01a830-f608-522a-9295-6d867e40f370"),
    ("example-volume", "c7b9d154-7fac-53bf-b33c-439817cad04e"),
])
def test_string_to_static_uuid_is_deterministic(input_value, expected):
    """Ensure UUID is deterministic and correctly computed."""
    assert string_to_static_uuid(input_value) == expected


class TestGetMount:
    """Tests for get_mount() function with timeout functionality."""

    def test_get_mount_found(self):
        """Test get_mount() returns mount when target path is found."""
        target_path = "/mnt/test"
        mock_mount = Mock()
        mock_mount.mountpoint = target_path
        mock_mount.device = "/dev/sda1"
        mock_mount.fstype = "ext4"

        with patch('psutil.disk_partitions') as mock_partitions:
            mock_partitions.return_value = [
                Mock(mountpoint="/", device="/dev/sda1", fstype="ext4"),
                mock_mount,
                Mock(mountpoint="/home", device="/dev/sda2", fstype="ext4"),
            ]

            result = get_mount(target_path, timeout=5)

            assert result is not None
            assert result.mountpoint == target_path
            assert result.device == "/dev/sda1"
            mock_partitions.assert_called_once_with(all=True)

    def test_get_mount_not_found(self):
        """Test get_mount() returns None when target path is not found."""
        target_path = "/mnt/nonexistent"

        with patch('psutil.disk_partitions') as mock_partitions:
            mock_partitions.return_value = [
                Mock(mountpoint="/", device="/dev/sda1", fstype="ext4"),
                Mock(mountpoint="/home", device="/dev/sda2", fstype="ext4"),
            ]

            result = get_mount(target_path, timeout=5)

            assert result is None
            mock_partitions.assert_called_once_with(all=True)

    def test_get_mount_timeout(self):
        """Test get_mount() raises TimeoutError when operation hangs."""
        target_path = "/mnt/hung"

        def slow_disk_partitions(all=True):
            # Simulate hung operation (unreachable NFS)
            time.sleep(10)
            return []

        with patch('psutil.disk_partitions', side_effect=slow_disk_partitions):
            with pytest.raises(TimeoutError) as exc_info:
                get_mount(target_path, timeout=2)

            assert "timed out after 2s" in str(exc_info.value)
            assert target_path in str(exc_info.value)
            assert "unreachable NFS" in str(exc_info.value)

    def test_get_mount_timeout_fast(self):
        """Test get_mount() timeout with very short timeout."""
        target_path = "/mnt/test"

        def slow_disk_partitions(all=True):
            time.sleep(5)
            return []

        with patch('psutil.disk_partitions', side_effect=slow_disk_partitions):
            with pytest.raises(TimeoutError) as exc_info:
                get_mount(target_path, timeout=1)

            assert "timed out after 1s" in str(exc_info.value)

    def test_get_mount_exception_propagation(self):
        """Test get_mount() propagates exceptions from psutil."""
        target_path = "/mnt/test"

        with patch('psutil.disk_partitions') as mock_partitions:
            mock_partitions.side_effect = PermissionError("Access denied")

            with pytest.raises(PermissionError) as exc_info:
                get_mount(target_path, timeout=5)

            assert "Access denied" in str(exc_info.value)

    def test_get_mount_thread_safety_multiple_calls(self):
        """Test get_mount() is thread-safe when called from multiple threads."""
        results = {}
        errors = {}

        def call_get_mount(thread_id, target_path, timeout):
            try:
                with patch('psutil.disk_partitions') as mock_partitions:
                    # Each thread gets different mock data
                    mock_mount = Mock()
                    mock_mount.mountpoint = target_path
                    mock_mount.device = f"/dev/sd{thread_id}"
                    mock_partitions.return_value = [mock_mount]

                    result = get_mount(target_path, timeout=timeout)
                    results[thread_id] = result
            except Exception as e:
                errors[thread_id] = e

        # Create multiple threads calling get_mount() simultaneously
        threads = []
        for i in range(5):
            thread = threading.Thread(
                target=call_get_mount,
                args=(i, f"/mnt/test{i}", 5)
            )
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # All threads should succeed without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"
        assert len(results) == 5

    def test_get_mount_empty_partitions(self):
        """Test get_mount() handles empty partition list."""
        with patch('psutil.disk_partitions') as mock_partitions:
            mock_partitions.return_value = []

            result = get_mount("/any/path", timeout=5)

            assert result is None

    def test_get_mount_matches_exact_path(self):
        """Test get_mount() matches exact path, not partial."""
        target_path = "/mnt/test"

        with patch('psutil.disk_partitions') as mock_partitions:
            mock_partitions.return_value = [
                Mock(mountpoint="/mnt", device="/dev/sda1"),
                Mock(mountpoint="/mnt/test123", device="/dev/sda2"),
                Mock(mountpoint="/mnt/testing", device="/dev/sda3"),
            ]

            result = get_mount(target_path, timeout=5)

            assert result is None  # None of the mounts match exactly

    def test_get_mount_daemon_thread_cleanup(self):
        """Test that daemon threads don't prevent process exit."""
        target_path = "/mnt/test"

        def slow_disk_partitions(all=True):
            time.sleep(100)  # Very long sleep
            return []

        with patch('psutil.disk_partitions', side_effect=slow_disk_partitions):
            try:
                get_mount(target_path, timeout=0.5)
            except TimeoutError:
                pass


@pytest.mark.parametrize("value, expected", [
    # True values
    ("true", True),
    ("True", True),
    ("TRUE", True),
    ("yes", True),
    ("Yes", True),
    ("YES", True),
    ("on", True),
    ("On", True),
    ("ON", True),
    ("1", True),
    ("  true  ", True),  # with whitespace
    # False values
    ("false", False),
    ("False", False),
    ("FALSE", False),
    ("no", False),
    ("No", False),
    ("NO", False),
    ("off", False),
    ("Off", False),
    ("OFF", False),
    ("0", False),
    ("  false  ", False),  # with whitespace
    # Already boolean
    (True, True),
    (False, False),
])
def test_yesno_to_bool_valid(value, expected):
    """Test yesno_to_bool with valid inputs"""
    assert yesno_to_bool(value) == expected


@pytest.mark.parametrize("value", [
    "invalid",
    "2",
    "maybe",
    "",
    "truee",
    "falsee",
    None,
    123,
    [],
    {},
])
def test_yesno_to_bool_invalid(value):
    """Test yesno_to_bool with invalid inputs raises ValueError"""
    with pytest.raises(ValueError, match="Cannot convert"):
        yesno_to_bool(value)


def test_parse_string_parameters_booleans():
    """Test boolean parsing in parse_string_parameters"""
    params = {
        "create_dir": "true",
        "enable_snapshot": "false",
        "auto_mount": "yes",
        "allow_delete": "no",
        "verbose": "on",
        "debug": "off",
    }
    result = parse_string_parameters(params)

    assert result["create_dir"] is True
    assert result["enable_snapshot"] is False
    assert result["auto_mount"] is True
    assert result["allow_delete"] is False
    assert result["verbose"] is True
    assert result["debug"] is False


def test_parse_string_parameters_integers():
    """Test integer parsing in parse_string_parameters"""
    params = {
        "capacity": "1000",
        "replica_count": "3",
        "timeout": "30",
        "zero": "0",  # This becomes False (boolean)
        "one": "1",   # This becomes True (boolean)
        "large_number": "9223372036854775807",
        "negative": "-42",
    }
    result = parse_string_parameters(params)

    assert result["capacity"] == 1000
    assert isinstance(result["capacity"], int)
    assert result["replica_count"] == 3
    assert isinstance(result["replica_count"], int)
    assert result["timeout"] == 30
    assert isinstance(result["timeout"], int)
    assert result["zero"] is False  # "0" is treated as boolean
    assert result["one"] is True    # "1" is treated as boolean
    assert result["large_number"] == 9223372036854775807
    assert result["negative"] == -42


def test_parse_string_parameters_floats():
    """Test float parsing in parse_string_parameters"""
    params = {
        "ratio": "1.5",
        "timeout": "30.5",
        "percentage": "99.99",
        "scientific": "1.5e10",
        "negative_float": "-3.14",
        "with_decimal": "100.0",
    }
    result = parse_string_parameters(params)

    assert result["ratio"] == 1.5
    assert isinstance(result["ratio"], float)
    assert result["timeout"] == 30.5
    assert isinstance(result["timeout"], float)
    assert result["percentage"] == 99.99
    assert result["scientific"] == 1.5e10
    assert result["negative_float"] == -3.14
    assert result["with_decimal"] == 100.0


def test_parse_string_parameters_strings():
    """Test that strings stay as strings"""
    params = {
        "name": "my-volume",
        "policy": "s3_default_policy",
        "path": "/exports/bucket",
        "description": "This is a test volume",
        "protocols": "NFS,SMB",
        "empty": "",
    }
    result = parse_string_parameters(params)

    assert result["name"] == "my-volume"
    assert isinstance(result["name"], str)
    assert result["policy"] == "s3_default_policy"
    assert result["path"] == "/exports/bucket"
    assert result["description"] == "This is a test volume"
    assert result["protocols"] == "NFS,SMB"
    assert result["empty"] == ""


def test_parse_string_parameters_mixed():
    """Test mixed types in parse_string_parameters"""
    params = {
        "create_dir": "true",
        "capacity": "1000",
        "ratio": "1.5",
        "name": "test-volume",
        "replicas": "3",
        "enabled": "yes",
        "path": "/data/volumes",
    }
    result = parse_string_parameters(params)

    assert result == {
        "create_dir": True,
        "capacity": 1000,
        "ratio": 1.5,
        "name": "test-volume",
        "replicas": 3,
        "enabled": True,
        "path": "/data/volumes",
    }


def test_parse_string_parameters_edge_cases():
    """Test edge cases in parse_string_parameters"""
    # Empty dict
    assert parse_string_parameters({}) == {}

    # Values with whitespace
    params = {
        "bool_with_space": "  true  ",
        "number_with_space": "  100  ",
    }
    result = parse_string_parameters(params)
    assert result["bool_with_space"] is True
    assert result["number_with_space"] == 100

    # Mixed case booleans
    params = {
        "upper": "TRUE",
        "lower": "false",
        "mixed": "Yes",
    }
    result = parse_string_parameters(params)
    assert result["upper"] is True
    assert result["lower"] is False
    assert result["mixed"] is True


def test_parse_string_parameters_non_string_values():
    """Test that non-string values are kept as-is"""
    params = {
        "already_bool": True,
        "already_int": 42,
        "already_float": 3.14,
        "string_value": "test",
    }
    result = parse_string_parameters(params)

    assert result["already_bool"] is True
    assert result["already_int"] == 42
    assert result["already_float"] == 3.14
    assert result["string_value"] == "test"


def test_parse_string_parameters_ambiguous_strings():
    """Test strings that could be confused with numbers or booleans"""
    params = {
        "looks_like_bool": "truee",  # Not exactly "true"
        "looks_like_number": "123abc",  # Has letters
        "looks_like_float": "1.2.3",  # Invalid float
        "version": "4.0.1",  # Could be mistaken for float
    }
    result = parse_string_parameters(params)

    # All should remain as strings since they don't match patterns
    assert result["looks_like_bool"] == "truee"
    assert isinstance(result["looks_like_bool"], str)
    assert result["looks_like_number"] == "123abc"
    assert isinstance(result["looks_like_number"], str)
    assert result["looks_like_float"] == "1.2.3"
    assert isinstance(result["looks_like_float"], str)
    assert result["version"] == "4.0.1"
    assert isinstance(result["version"], str)


@pytest.mark.parametrize("base_path, replacement_path, expected", [
    # Basic replacement - replace 2 segments with 2 segments
    ("/foo/bar/biz", "/zoo/rar", "/zoo/rar/biz"),

    # Replace 1 segment with 2 segments (replacement is longer)
    ("/k8s", "/replication/volumes", "/replication/volumes"),

    # Replace 2 segments with 2 segments in deep hierarchy
    ("/production/team-a/app1/data", "/backup/dr-site", "/backup/dr-site/app1/data"),

    # Replace 1 segment with 1 segment
    ("/k8s/volumes", "/replication", "/replication/volumes"),

    # Replace 1 segment with 1 segment (keeps b/c/d/e)
    ("/a/b/c/d/e", "/x", "/x/b/c/d/e"),

    # Replacement path equals base path length
    ("/a/b/c", "/x/y/z", "/x/y/z"),

    # Replacement path longer than base path
    ("/a/b", "/x/y/z/w", "/x/y/z/w"),

    # Single segment paths
    ("/data", "/backup", "/backup"),

    # Deep hierarchies (replaces first 2 segments: var, lib)
    ("/var/lib/kubernetes/volumes/pvc-123", "/mnt/replication", "/mnt/replication/kubernetes/volumes/pvc-123"),

    # Root paths
    ("/", "/backup", "/backup"),

    # Trailing slashes (should be handled same as without)
    ("/foo/bar/", "/zoo", "/zoo/bar"),

    # Mixed trailing slashes
    ("/foo/bar/biz/", "/zoo/rar/", "/zoo/rar/biz"),
])
def test_replace_path_prefix_valid_cases(base_path, replacement_path, expected):
    """Test replace_path_prefix with various valid inputs"""
    result = replace_path_prefix(base_path, replacement_path)
    assert result == expected


@pytest.mark.parametrize("base_path, replacement_path, expected", [
    # None replacement path - should return base path unchanged
    ("/foo/bar/biz", None, "/foo/bar/biz"),

    # Empty string replacement - should return base path unchanged
    ("/k8s/volumes", "", "/k8s/volumes"),

    # Base path with None replacement
    ("/production/data", None, "/production/data"),
])
def test_replace_path_prefix_none_or_empty_replacement(base_path, replacement_path, expected):
    """Test replace_path_prefix when replacement is None or empty"""
    result = replace_path_prefix(base_path, replacement_path)
    assert result == expected


def test_replace_path_prefix_preserves_structure():
    """Test that relative hierarchy is preserved after replacement"""
    # Multi-level structure preservation
    base = "/production/us-east/team-alpha/app/volumes/data"
    replacement = "/backup/dr"
    result = replace_path_prefix(base, replacement)

    # Should replace first 2 segments (/production/us-east) with /backup/dr
    # and keep the rest (team-alpha/app/volumes/data)
    assert result == "/backup/dr/team-alpha/app/volumes/data"


def test_replace_path_prefix_kubernetes_example():
    """Test typical Kubernetes volume replication scenario"""
    # Primary cluster path
    base = "/k8s/pvc-6c5315db-5855-4ab2-a5a0-e4119718baa8"

    # Replicate to /replication prefix
    replacement = "/replication"
    result = replace_path_prefix(base, replacement)

    # Should replace /k8s with /replication
    assert result == "/replication/pvc-6c5315db-5855-4ab2-a5a0-e4119718baa8"


def test_replace_path_prefix_same_depth():
    """Test replacement with same number of segments"""
    base = "/primary/data/volumes"
    replacement = "/secondary/backup/replicated"
    result = replace_path_prefix(base, replacement)

    # All segments replaced (same depth)
    assert result == "/secondary/backup/replicated"


def test_replace_path_prefix_edge_cases():
    """Test edge cases in path replacement"""
    # Multiple leading slashes (normalized to single)
    base = "///foo///bar///biz"
    replacement = "/zoo/rar"
    result = replace_path_prefix(base, replacement)
    assert result == "/zoo/rar/biz"

    # Path with only slashes
    assert replace_path_prefix("/", "/backup") == "/backup"

    # Empty base path segments
    base = "/foo//bar/biz"  # Double slash creates empty segment
    replacement = "/zoo"
    result = replace_path_prefix(base, replacement)
    # Empty segments are filtered out
    assert result == "/zoo/bar/biz"
