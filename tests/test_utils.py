import pytest
from unittest.mock import Mock, patch
import threading
import time
from vast_csi.utils import (
    is_ver_nfs4_present, 
    generate_ip_range, 
    wrap_ipv6, 
    string_to_static_uuid,
    get_mount
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
