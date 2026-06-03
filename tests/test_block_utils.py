import json
from unittest.mock import patch, MagicMock
import pytest
from plumbum import local
from plumbum.commands.processes import ProcessExecutionError, ProcessTimedOut
from easypy.bunch import bunchify
from easypy.collections import listify
from vast_csi.block_utils import (
    get_connected_session,
    get_hostnqn_from_sysfs,
    verify_device_quiesced,
)
from vast_csi.exceptions import DeviceNotQuiesced

ver_2x_nvme_out = [
    {
        "HostNQN": "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9",
        "HostID": "94300544-77e5-4544-a504-cf6778a60f5d",
        "Subsystems": [
            {
                "Name": "nvme-subsys1",
                "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
                "IOPolicy": "round-robin",
                "Paths": [
                    {
                        "Name": "nvme1",
                        "Transport": "tcp",
                        "Address": "traddr=172.21.112.9,trsvcid=4420",
                        "State": "live",
                    },
                    {
                        "Name": "nvme1",
                        "Transport": "tcp",
                        "Address": "traddr=172.21.112.8,trsvcid=4420",
                        "State": "live",
                    },
                ],
            }
        ],
    }
]

ver_1x_nvme_out = {
    "Subsystems": [
        {
            "Name": "nvme-subsys0",
            "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
            "Paths": [
                {
                    "Name": "nvme1",
                    "Transport": "tcp",
                    "Address": "traddr=172.21.112.9,trsvcid=4420",
                    "State": "live",
                },
                {
                    "Name": "nvme1",
                    "Transport": "tcp",
                    "Address": "traddr=172.21.112.8,trsvcid=4420",
                    "State": "live",
                },
            ],
        }
    ]
}


@pytest.mark.parametrize("sub_sys_out", [ver_1x_nvme_out, ver_2x_nvme_out])
def test_get_connected_session(sub_sys_out):
    """
    Output of nvme list-subsys command is different for nvme v1.x and v2.x.
    Purpose of this test is to verify parsing consistency.
    """
    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"
    unknown_subsys_nqn = "nqn.2024-08.com.vastdata:898f9ee2-cc09-5130-b8e4-ede79286dcc6:default:subsystem-4"
    host_nqn = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"

    # Mock list_nvme_sessions to avoid hostcmd dependency
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        # Handle both v1.x (dict) and v2.x (list) formats
        mock_list.return_value = listify(bunchify(sub_sys_out))
        
        # For nvme-cli 1.x (no HostNQN field), mock sysfs fallback
        # Check if this is v1.x format by checking if HostNQN is in the data
        is_v1 = isinstance(sub_sys_out, dict) or (isinstance(sub_sys_out, list) and "HostNQN" not in sub_sys_out[0])
        
        if is_v1:
            # For v1.x, mock the sysfs fallback to return the expected HostNQN
            with patch("vast_csi.block_utils.get_hostnqn_from_sysfs", MagicMock(return_value=host_nqn)):
                session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=host_nqn)
                assert session
                session = get_connected_session(subsystem_nqn=unknown_subsys_nqn, host_nqn=host_nqn)
                assert not session
        else:
            # For v2.x, HostNQN is included, no sysfs fallback needed
            session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=host_nqn)
            assert session
            session = get_connected_session(subsystem_nqn=unknown_subsys_nqn, host_nqn=host_nqn)
            assert not session

def test_get_hostnqn_from_sysfs_success():
    """Test reading HostNQN from sysfs when nvme controller exists."""
    expected_hostnqn = "nqn.2014-08.org.nvmexpress:uuid:12345678-1234-1234-1234-123456789abc"
    
    # Create a mock subsystem object with Paths
    mock_subsystem = bunchify({
        "Name": "nvme-subsys0",
        "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
        "Paths": [
            {"Name": "nvme0", "Transport": "tcp", "State": "live"}
        ]
    })
    
    # Mock hostnqn file
    mock_hostnqn_file = MagicMock()
    mock_hostnqn_file.exists.return_value = True
    mock_hostnqn_file.read.return_value = f"{expected_hostnqn}\n"
    
    # Mock NVME_CLASS_PATH / controller_name / "hostnqn"
    mock_nvme_class_path = MagicMock()
    mock_nvme_class_path.__truediv__ = lambda self, key: MagicMock(__truediv__=lambda s, k: mock_hostnqn_file)

    with patch("vast_csi.block_utils.NVME_CLASS_PATH", mock_nvme_class_path):
        result = get_hostnqn_from_sysfs(mock_subsystem)
        assert result == expected_hostnqn


def test_get_hostnqn_from_sysfs_no_paths():
    """Test reading HostNQN from sysfs when subsystem has no paths."""
    # Create a mock subsystem object with no Paths
    mock_subsystem = bunchify({
        "Name": "nvme-subsys0",
        "NQN": "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock",
        "Paths": []
    })
    
    result = get_hostnqn_from_sysfs(mock_subsystem)
    assert result is None


def test_get_connected_session_nvme1x_wrong_hostnqn():
    """
    Test VCSI-356 scenario: nvme-cli 1.x (no HostNQN field) with different HostNQN in sysfs.

    This simulates the xAI bug where:
    1. Host was pre-connected to VAST with a different HostNQN (outside of CSI)
    2. nvme-cli 1.x doesn't report HostNQN field
    3. Old buggy code would assume HostNQN matches (using default parameter)
    4. New fixed code reads from sysfs and correctly detects the mismatch
    """
    # CSI expects this HostNQN
    expected_host_nqn = "nqn.2014-08.com.vastcsiblock:node-123:tenant-default"

    # But the actual connected host has a different HostNQN
    actual_host_nqn = "nqn.2014-08.org.nvmexpress:uuid:pre-existing-connection"

    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"

    # Mock nvme-cli 1.x output (no HostNQN field)
    nvme_1x_output = ver_1x_nvme_out

    # Create a mock for the nvme command that returns our test data
    mock_nvme_cmd = MagicMock(return_value=json.dumps(nvme_1x_output))
    
    # Mock list_nvme_sessions to avoid hostcmd dependency
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        # Simulate what list_nvme_sessions returns for nvme-cli 1.x
        mock_list.return_value = [bunchify(ver_1x_nvme_out)]
        
        with patch("vast_csi.block_utils.get_hostnqn_from_sysfs", MagicMock(return_value=actual_host_nqn)):
            # Should return None because HostNQN doesn't match
            session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=expected_host_nqn)
            assert session is None, "Should not find session when HostNQN doesn't match"


def test_get_connected_session_nvme1x_correct_hostnqn():
    """
    Test that nvme-cli 1.x with matching HostNQN (read from sysfs) correctly finds the session.
    """
    expected_host_nqn = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"
    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"

    # Mock list_nvme_sessions to avoid hostcmd dependency
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        # Simulate what list_nvme_sessions returns for nvme-cli 1.x
        mock_list.return_value = [bunchify(ver_1x_nvme_out)]
        
        with patch("vast_csi.block_utils.get_hostnqn_from_sysfs", MagicMock(return_value=expected_host_nqn)):
            # Should find the session because HostNQN matches
            session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=expected_host_nqn)
            assert session is not None, "Should find session when HostNQN matches"
            assert session.NQN == known_subsys_nqn


def test_get_connected_session_nvme1x_sysfs_unavailable():
    """
    Test that nvme-cli 1.x with unavailable sysfs correctly returns None (safe failure).

    This ensures we don't make the wrong assumption when we can't verify the HostNQN.
    """
    expected_host_nqn = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"
    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"

    # Mock list_nvme_sessions to avoid hostcmd dependency
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        # Simulate what list_nvme_sessions returns for nvme-cli 1.x
        mock_list.return_value = [bunchify(ver_1x_nvme_out)]
        
        with patch("vast_csi.block_utils.get_hostnqn_from_sysfs", MagicMock(return_value=None)):
            # Should return None because we can't verify HostNQN
            session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=expected_host_nqn)
            assert session is None, "Should not find session when HostNQN cannot be verified"


def test_get_connected_session_nvme2x_with_hostnqn():
    """
    Test that nvme-cli 2.x with HostNQN field works correctly (no sysfs fallback needed).
    """
    expected_host_nqn = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"
    known_subsys_nqn = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"

    # Mock list_nvme_sessions to avoid hostcmd dependency
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        # Simulate what list_nvme_sessions returns for nvme-cli 2.x (includes HostNQN)
        mock_list.return_value = [bunchify(ver_2x_nvme_out[0])]
        
        # get_hostnqn_from_sysfs should NOT be called when HostNQN is present
        with patch("vast_csi.block_utils.get_hostnqn_from_sysfs") as mock_sysfs:
            session = get_connected_session(subsystem_nqn=known_subsys_nqn, host_nqn=expected_host_nqn)
            assert session is not None
            assert session.NQN == known_subsys_nqn
            # Verify sysfs was NOT called (nvme-cli 2.x provides HostNQN)
            mock_sysfs.assert_not_called()


def test_get_connected_session_multiple_sessions_different_hostnqn():
    """
    Test multiple sessions with same subsystem NQN but different HostNQNs.
    
    This scenario can occur when:
    1. Multiple containers/namespaces on the same physical host connect to storage
    2. Each uses a different HostNQN for isolation
    3. We need to ensure we select the correct session based on HostNQN
    """
    # Two different HostNQNs
    host_nqn_1 = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-1b0f972641c9"
    host_nqn_2 = "nqn.2014-08.org.nvmexpress:uuid:92772a1b-d036-4022-b441-3574335677"
    
    # Two different subsystem NQNs
    subsys_nqn_1 = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock"
    subsys_nqn_2 = "nqn.2024-08.com.vastdata:874c7d6d-aeed-5091-82b2-43ec05eee214:default:myblock2"
    
    # Mock data with multiple sessions
    multi_session_output = [
        {
            "HostNQN": host_nqn_1,
            "HostID": "94300544-77e5-4544-a504-cf6778a60f5d",
            "Subsystems": [
                {
                    "Name": "nvme-subsys1",
                    "NQN": subsys_nqn_1,
                    "IOPolicy": "round-robin",
                    "Paths": [
                        {
                            "Name": "nvme1",
                            "Transport": "tcp",
                            "Address": "traddr=172.21.112.9,trsvcid=4420",
                            "State": "live",
                        },
                    ],
                }
            ],
        },
        {
            "HostNQN": host_nqn_2,
            "HostID": "23455455678888",
            "Subsystems": [
                {
                    "Name": "nvme-subsys2",
                    "NQN": subsys_nqn_2,
                    "IOPolicy": "round-robin",
                    "Paths": [
                        {
                            "Name": "nvme2",
                            "Transport": "tcp",
                            "Address": "traddr=172.21.112.9,trsvcid=4420",
                            "State": "live",
                        },
                    ],
                }
            ],
        },
    ]
    
    with patch("vast_csi.block_utils.list_nvme_sessions") as mock_list:
        mock_list.return_value = [bunchify(session) for session in multi_session_output]
        
        # Test 1: Request session 1 with host_nqn_1 and subsys_nqn_1
        session = get_connected_session(subsystem_nqn=subsys_nqn_1, host_nqn=host_nqn_1)
        assert session is not None, "Should find session 1"
        assert session.NQN == subsys_nqn_1, "Should return correct subsystem NQN"
        assert session.Name == "nvme-subsys1", "Should return correct subsystem name"
        
        # Test 2: Request session 2 with host_nqn_2 and subsys_nqn_2
        session = get_connected_session(subsystem_nqn=subsys_nqn_2, host_nqn=host_nqn_2)
        assert session is not None, "Should find session 2"
        assert session.NQN == subsys_nqn_2, "Should return correct subsystem NQN"
        assert session.Name == "nvme-subsys2", "Should return correct subsystem name"
        
        # Test 3: Request subsys_nqn_1 but with wrong host_nqn_2 (should fail)
        session = get_connected_session(subsystem_nqn=subsys_nqn_1, host_nqn=host_nqn_2)
        assert session is None, "Should NOT find session when HostNQN doesn't match"
        
        # Test 4: Request subsys_nqn_2 but with wrong host_nqn_1 (should fail)
        session = get_connected_session(subsystem_nqn=subsys_nqn_2, host_nqn=host_nqn_1)
        assert session is None, "Should NOT find session when HostNQN doesn't match"
        
        # Test 5: Request non-existent subsystem (should fail)
        session = get_connected_session(
            subsystem_nqn="nqn.2024-08.com.vastdata:nonexistent",
            host_nqn=host_nqn_1
        )
        assert session is None, "Should NOT find non-existent subsystem"


def _make_fake_sysfs(tmp_path, device_name, *, inflight="0 0", holders=()):
    """Build a /sys/block/<dev> stand-in under tmp_path.

    Returns the local.path object to be patched in as BLOCK_DEVICE_INFO_PATH.
    """
    sys_block_root = local.path(str(tmp_path / "sys" / "block"))
    sys_block_root.mkdir()
    dev_dir = sys_block_root / device_name
    dev_dir.mkdir()
    (dev_dir / "inflight").write(inflight)
    holders_dir = dev_dir / "holders"
    holders_dir.mkdir()
    for h in holders:
        (holders_dir / h).write("")
    return sys_block_root


@pytest.fixture
def fake_blockdev_cmd():
    """Patch cmd.blockdev with a MagicMock supporting cmd.blockdev[...].run(timeout=...)."""
    mock_blockdev = MagicMock()
    mock_blockdev.__getitem__ = MagicMock(return_value=mock_blockdev)
    mock_blockdev.run = MagicMock(return_value=None)
    with patch("vast_csi.block_utils.cmd") as mock_cmd:
        mock_cmd.blockdev = mock_blockdev
        yield mock_blockdev


class TestVerifyDeviceQuiesced:
    """Cover all failure paths of verify_device_quiesced."""

    def test_idle_device_passes(self, tmp_path, fake_blockdev_cmd):
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40", inflight="0 0", holders=())
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            verify_device_quiesced("/dev/nvme3n40", timeout_s=1)
        fake_blockdev_cmd.__getitem__.assert_called_with(("--flushbufs", "/dev/nvme3n40"))
        fake_blockdev_cmd.run.assert_called_once()

    def test_raises_when_holders_present(self, tmp_path, fake_blockdev_cmd):
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40", holders=("dm-7",))
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            with pytest.raises(DeviceNotQuiesced) as exc:
                verify_device_quiesced("/dev/nvme3n40", timeout_s=1)
        assert "holders" in str(exc.value)
        assert "dm-7" in str(exc.value)
        # When holders fails we must not even attempt flushbufs.
        fake_blockdev_cmd.run.assert_not_called()

    def test_raises_when_flushbufs_times_out(self, tmp_path, fake_blockdev_cmd):
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40")
        fake_blockdev_cmd.run.side_effect = ProcessTimedOut("hang", ["blockdev"])
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            with pytest.raises(DeviceNotQuiesced) as exc:
                verify_device_quiesced("/dev/nvme3n40", timeout_s=1)
        assert "flushbufs" in str(exc.value)

    def test_raises_when_flushbufs_errors(self, tmp_path, fake_blockdev_cmd):
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40")
        fake_blockdev_cmd.run.side_effect = ProcessExecutionError(
            ["blockdev"], 1, "", "I/O error"
        )
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            with pytest.raises(DeviceNotQuiesced) as exc:
                verify_device_quiesced("/dev/nvme3n40", timeout_s=1)
        assert "flushbufs" in str(exc.value)

    def test_raises_when_inflight_never_drains(self, tmp_path, fake_blockdev_cmd):
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40", inflight="5 12")
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            with pytest.raises(DeviceNotQuiesced) as exc:
                # timeout_s=0 makes the poll loop exit immediately.
                verify_device_quiesced("/dev/nvme3n40", timeout_s=0)
        msg = str(exc.value)
        assert "inflight" in msg
        assert "reads=5" in msg
        assert "writes=12" in msg

    def test_skips_when_no_sysfs_entry(self, tmp_path, fake_blockdev_cmd):
        # If the resolved basename has no /sys/block/<name> entry (e.g., a
        # partition like nvme0n1p1 which lives under its parent's directory,
        # or a device already torn down), treat as out-of-scope and skip.
        sys_block = _make_fake_sysfs(tmp_path, "nvme3n40")
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            verify_device_quiesced("/dev/nvme0n1p1", timeout_s=1)  # must not raise
        fake_blockdev_cmd.run.assert_not_called()

    def test_resolves_luks_symlink_to_dm_device(self, tmp_path, fake_blockdev_cmd):
        # LUKS volumes stage from /dev/mapper/luks-<uuid>, which is a symlink
        # to /dev/dm-N. The check must resolve the symlink and operate on the
        # dm-N node so dm-crypt's sysfs counters are read and blockdev runs
        # against the resolved path.
        import os as _os
        sys_block = _make_fake_sysfs(tmp_path, "dm-7", inflight="0 0", holders=())
        # Build fake /dev/mapper/luks-xxx -> /dev/dm-7
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "dm-7").write_text("")  # target must exist for realpath
        mapper_dir = dev_dir / "mapper"
        mapper_dir.mkdir()
        luks_link = mapper_dir / "luks-abcd-1234"
        _os.symlink(str(dev_dir / "dm-7"), str(luks_link))

        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            verify_device_quiesced(str(luks_link), timeout_s=1)

        # blockdev must be invoked against the RESOLVED path, not the symlink.
        fake_blockdev_cmd.__getitem__.assert_called_with(
            ("--flushbufs", str(dev_dir / "dm-7"))
        )
        fake_blockdev_cmd.run.assert_called_once()

    def test_raises_when_luks_dm_has_inflight(self, tmp_path, fake_blockdev_cmd):
        # Storm scenario on an encrypted volume: dm-N still has inflight I/O.
        # Must raise just like the unencrypted case.
        import os as _os
        sys_block = _make_fake_sysfs(tmp_path, "dm-7", inflight="2 9", holders=())
        dev_dir = tmp_path / "dev"
        dev_dir.mkdir()
        (dev_dir / "dm-7").write_text("")
        mapper_dir = dev_dir / "mapper"
        mapper_dir.mkdir()
        luks_link = mapper_dir / "luks-abcd-1234"
        _os.symlink(str(dev_dir / "dm-7"), str(luks_link))

        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block):
            with pytest.raises(DeviceNotQuiesced) as exc:
                verify_device_quiesced(str(luks_link), timeout_s=0)
        msg = str(exc.value)
        assert "dm-7" in msg
        assert "reads=2" in msg and "writes=9" in msg

    def test_skips_drain_when_inflight_unreadable(self, tmp_path, fake_blockdev_cmd):
        # Regression: _read_inflight returns (-1, -1) when the file is missing
        # or malformed. The drain loop must treat that as "unknown -> skip",
        # NOT as "non-zero -> raise". Otherwise default-on quiescence breaks
        # every unstage on kernels that don't expose /sys/block/<dev>/inflight
        # in the expected format.
        sys_block_root = local.path(str(tmp_path / "sys" / "block"))
        sys_block_root.mkdir()
        dev_dir = sys_block_root / "nvme3n40"
        dev_dir.mkdir()
        (dev_dir / "holders").mkdir()
        # NOTE: deliberately no "inflight" file -> _read_inflight returns (-1,-1)
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", sys_block_root):
            verify_device_quiesced("/dev/nvme3n40", timeout_s=1)  # must not raise
        fake_blockdev_cmd.run.assert_called_once()

    def test_skips_when_sys_block_missing(self, tmp_path, fake_blockdev_cmd):
        # Device gone from sysfs (already cleaned up) -- best-effort skip.
        empty_sys_block = local.path(str(tmp_path / "empty"))
        empty_sys_block.mkdir()
        with patch("vast_csi.block_utils.BLOCK_DEVICE_INFO_PATH", empty_sys_block):
            verify_device_quiesced("/dev/nvme3n40", timeout_s=1)  # must not raise
        fake_blockdev_cmd.run.assert_not_called()
