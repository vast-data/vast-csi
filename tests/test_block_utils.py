import json
from unittest.mock import patch, MagicMock
import pytest
from easypy.bunch import bunchify
from easypy.collections import listify
from vast_csi.block_utils import get_connected_session, get_hostnqn_from_sysfs

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


def test_ensure_nvme_tcp_skips_modprobe_when_loaded(monkeypatch):
    from vast_csi.block_utils import _ensure_nvme_tcp

    monkeypatch.setattr("vast_csi.block_utils.NVME_TCP_MODULE.exists", lambda: True)
    with patch("vast_csi.block_utils.host_commands.modprobe.get_executable") as mock_get_executable:
        assert _ensure_nvme_tcp() is True
        mock_get_executable.assert_not_called()


def test_ensure_nvme_tcp_returns_false_when_module_missing(tmp_path, monkeypatch):
    from plumbum import local, ProcessExecutionError
    from vast_csi.block_utils import _ensure_nvme_tcp
    from vast_csi.filesystem_utils import HostCommandAdapter, host_commands

    host_root = tmp_path / "host"
    host_root.mkdir()
    monkeypatch.setattr(HostCommandAdapter, "HOST_MOUNT", local.path(host_root))
    monkeypatch.setattr("vast_csi.block_utils.NVME_TCP_MODULE.exists", lambda: False)

    with patch.object(
        host_commands.modprobe,
        "get_executable",
        side_effect=ProcessExecutionError(
            retcode=1, stdout="", stderr="modprobe failed", argv=["modprobe", "nvme-tcp"]
        ),
    ):
        assert _ensure_nvme_tcp() is False


def test_try_nvme_probes_rejects_invalid_search_dirs(monkeypatch):
    from vast_csi.block_utils import try_nvme_probes

    monkeypatch.setattr("vast_csi.block_utils._ensure_nvme_tcp", lambda: True)
    monkeypatch.setenv("X_CSI_BLOCK_HOST_BINARY_SEARCH_DIRS", "usr/bin")

    with patch("vast_csi.block_utils.hostnvme") as mock_hostnvme, patch(
        "vast_csi.block_utils.logger.error"
    ) as mock_error:
        try_nvme_probes()
        mock_hostnvme.assert_not_called()
        mock_error.assert_called_once()
        assert mock_error.call_args[0][0] == "Invalid X_CSI_BLOCK_HOST_BINARY_SEARCH_DIRS: %s"
        assert "search dir must be absolute" in str(mock_error.call_args[0][1])

