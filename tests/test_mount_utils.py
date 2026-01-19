"""Tests for mount/umount functions with logging and timeout support."""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from plumbum import ProcessExecutionError
from plumbum.commands.processes import ProcessTimedOut

from easypy.units import Duration


# Mock CONF before importing the modules
class MockConf:
    mount_umount_timeout = 30
    mock_vast = False


@pytest.fixture
def mock_conf():
    """Fixture to provide a mock configuration."""
    return MockConf()

class TestCsiMount:
    """Tests for CSI plugin mount function."""

    def test_mount_success(self, mock_conf):
        """Test successful mount operation logs before and after with duration."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = mock_run

            with (
                patch.object(csi.cmd, "mount", mock_mount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                csi.mount("/dev/sda1", "/mnt/test", flags="ro,noexec")

                # Verify logging was called
                assert mock_log_info.call_count >= 2
                # Check that we logged before mounting
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "Mounting" in first_call
                assert "/dev/sda1" in first_call
                assert "/mnt/test" in first_call
                assert "timeout: 30s" in first_call
                # Check that we logged after mounting
                last_call = mock_log_info.call_args_list[-1][0][0]
                assert "succeeded" in last_call

    def test_mount_timeout(self, mock_conf):
        """Test mount operation that times out."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi
            from vast_csi.exceptions import MountFailed

            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = MagicMock(side_effect=ProcessTimedOut(
                "mount command timed out", MagicMock()
            ))

            with (
                patch.object(csi.cmd, "mount", mock_mount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                with pytest.raises(MountFailed) as exc_info:
                    csi.mount("/dev/sda1", "/mnt/test")

                # Verify exception detail contains timeout info
                assert "timed out" in exc_info.value.detail

    def test_mount_execution_error(self, mock_conf):
        """Test mount operation that fails with execution error."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi
            from vast_csi.exceptions import MountFailed

            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = MagicMock(side_effect=ProcessExecutionError(
                argv=["mount"], retcode=1, stdout="", stderr="mount: /mnt/test: mount point does not exist"
            ))

            with (
                patch.object(csi.cmd, "mount", mock_mount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info"),
            ):
                with pytest.raises(MountFailed) as exc_info:
                    csi.mount("/dev/sda1", "/mnt/test")

                # Verify exception detail contains stderr
                assert "mount point does not exist" in exc_info.value.detail


class TestCsiUmount:
    """Tests for CSI plugin umount function."""

    def test_umount_success(self, mock_conf):
        """Test successful umount operation logs before and after with duration."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi
            from vast_csi.exceptions import UmountTimedOut

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = mock_run

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                result = csi.umount("/mnt/test")

                assert result is True
                # Verify logging was called
                assert mock_log_info.call_count >= 2
                # Check that we logged before unmounting
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "Unmounting" in first_call
                assert "/mnt/test" in first_call
                # Check that we logged after unmounting
                last_call = mock_log_info.call_args_list[-1][0][0]
                assert "succeeded" in last_call

    def test_umount_timeout(self, mock_conf):
        """Test umount operation that times out."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi
            from vast_csi.exceptions import UmountTimedOut

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessTimedOut(
                "umount command timed out", MagicMock()
            ))

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info"),
            ):
                with pytest.raises(UmountTimedOut) as exc_info:
                    csi.umount("/mnt/test")

                # Verify exception message
                assert "timed out" in str(exc_info.value)
                assert "30s" in str(exc_info.value)

    def test_umount_not_mounted_ignored(self, mock_conf):
        """Test umount with 'not mounted' error when ignore_not_mounted=True."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessExecutionError(
                argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: not mounted"
            ))

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                result = csi.umount("/mnt/test", ignore_not_mounted=True)

                assert result is False
                # Verify that "not mounted (ignored)" was logged with elapsed time
                log_calls = [call[0][0] for call in mock_log_info.call_args_list]
                assert any("not mounted (ignored)" in call for call in log_calls)

    def test_umount_not_mounted_warning(self, mock_conf):
        """Test umount with 'not mounted' error when ignore_not_mounted=False."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessExecutionError(
                argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: not mounted"
            ))

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info"),
                patch.object(csi.logger, "warning") as mock_log_warning,
            ):
                result = csi.umount("/mnt/test", ignore_not_mounted=False)

                assert result is False
                # Verify warning was logged
                assert mock_log_warning.call_count >= 1
                warning_call = mock_log_warning.call_args_list[0][0][0]
                assert "not mounted" in warning_call

    def test_umount_other_error_raises(self, mock_conf):
        """Test umount with other errors raises exception."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessExecutionError(
                argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: device is busy"
            ))

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info"),
            ):
                with pytest.raises(ProcessExecutionError):
                    csi.umount("/mnt/test")


class TestBlockMount:
    """Tests for Block plugin mount function."""

    def test_mount_success_bind(self, mock_conf):
        """Test successful bind mount operation."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = mock_run

            with (
                patch.object(block.cmd, "mount", mock_mount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info") as mock_log_info,
            ):
                block.mount("/dev/nvme0n1", "/mnt/test", bind=True)

                # Verify logging was called
                assert mock_log_info.call_count >= 2
                # Check that we logged before mounting with bind type
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "Mounting" in first_call
                assert "bind" in first_call

    def test_mount_success_with_fs_type(self, mock_conf):
        """Test successful mount operation with filesystem type."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = mock_run

            with (
                patch.object(block.cmd, "mount", mock_mount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info") as mock_log_info,
            ):
                block.mount("/dev/nvme0n1", "/mnt/test", fs_type="ext4", flags=["ro", "noexec"])

                # Verify logging was called
                assert mock_log_info.call_count >= 2
                # Check that we logged with fs_type
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "fs_type=ext4" in first_call
                assert "ro,noexec" in first_call

    def test_mount_timeout(self, mock_conf):
        """Test mount operation that times out."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block
            from vast_csi.exceptions import MountFailed

            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = MagicMock(side_effect=ProcessTimedOut(
                "mount command timed out", MagicMock()
            ))

            with (
                patch.object(block.cmd, "mount", mock_mount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info"),
            ):
                with pytest.raises(MountFailed) as exc_info:
                    block.mount("/dev/nvme0n1", "/mnt/test")

                # Verify exception detail contains timeout info
                assert "timed out" in exc_info.value.detail


class TestBlockUmount:
    """Tests for Block plugin umount function."""

    def test_umount_success(self, mock_conf):
        """Test successful umount operation."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = mock_run

            with (
                patch.object(block.cmd, "umount", mock_umount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info") as mock_log_info,
            ):
                result = block.umount("/mnt/test")

                assert result is True
                # Verify logging was called
                assert mock_log_info.call_count >= 2
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "Unmounting" in first_call
                last_call = mock_log_info.call_args_list[-1][0][0]
                assert "succeeded" in last_call

    def test_umount_timeout(self, mock_conf):
        """Test umount operation that times out."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block
            from vast_csi.exceptions import UmountTimedOut

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessTimedOut(
                "umount command timed out", MagicMock()
            ))

            with (
                patch.object(block.cmd, "umount", mock_umount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info"),
            ):
                with pytest.raises(UmountTimedOut) as exc_info:
                    block.umount("/mnt/test")

                assert "timed out" in str(exc_info.value)

    def test_umount_safe_wrapper(self, mock_conf):
        """Test umount_safe is a wrapper for umount with ignore_not_mounted=True."""
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessExecutionError(
                argv=["umount"], retcode=1, stdout="", stderr="not mounted"
            ))

            with (
                patch.object(block.cmd, "umount", mock_umount_cmd),
                patch.object(block, "CONF", mock_conf),
                patch.object(block.logger, "info"),
            ):
                # Should not raise
                block.umount_safe("/mnt/test")


class TestTimeoutConfiguration:
    """Tests to verify custom timeout values are respected."""

    def test_custom_timeout_value(self):
        """Test that custom timeout value is passed to the command."""

        class CustomConf:
            mount_umount_timeout = 60  # Custom 60 second timeout
            mock_vast = False

        with patch("vast_csi.plugins.csi.CONF", CustomConf()):
            from vast_csi.plugins import csi

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = mock_run

            with (
                patch.object(csi.cmd, "mount", mock_mount_cmd),
                patch.object(csi, "CONF", CustomConf()),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                csi.mount("/dev/sda1", "/mnt/test")

                # Verify the timeout was passed to run()
                mock_run.assert_called_once()
                call_kwargs = mock_run.call_args[1]
                assert call_kwargs["timeout"] == 60

                # Verify custom timeout was logged
                first_call = mock_log_info.call_args_list[0][0][0]
                assert "timeout: 60s" in first_call


class TestDurationLogging:
    """Tests to verify duration is properly logged using easypy timing."""

    def test_mount_duration_logged(self, mock_conf):
        """Test that mount duration is logged on success using Duration format."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi

            mock_run = MagicMock(return_value=(0, "", ""))
            mock_mount_cmd = MagicMock()
            mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
            mock_mount_cmd.run = mock_run

            with (
                patch.object(csi.cmd, "mount", mock_mount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info") as mock_log_info,
            ):
                csi.mount("/dev/sda1", "/mnt/test")

                # Check that duration was logged with Duration format (e.g., "100ms", "1.5s")
                last_call = mock_log_info.call_args_list[-1][0][0]
                assert "succeeded in" in last_call
                # Duration uses units like 'ms', 's', 'm' - check for common patterns
                assert any(unit in last_call for unit in ["ms", "us", "ns", "s:"])

    def test_umount_timeout_exception_message(self, mock_conf):
        """Test that umount timeout exception contains proper message."""
        with patch("vast_csi.plugins.csi.CONF", mock_conf):
            from vast_csi.plugins import csi
            from vast_csi.exceptions import UmountTimedOut

            mock_umount_cmd = MagicMock()
            mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
            mock_umount_cmd.run = MagicMock(side_effect=ProcessTimedOut(
                "umount command timed out", MagicMock()
            ))

            with (
                patch.object(csi.cmd, "umount", mock_umount_cmd),
                patch.object(csi, "CONF", mock_conf),
                patch.object(csi.logger, "info"),
            ):
                with pytest.raises(UmountTimedOut) as exc_info:
                    csi.umount("/mnt/test")

                # Verify exception message contains timeout info
                assert "timed out" in str(exc_info.value)
                assert "30s" in str(exc_info.value)
