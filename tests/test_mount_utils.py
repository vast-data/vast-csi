"""Tests for mount/umount in filesystem_utils (used by NFS and block plugins)."""
import pytest
from unittest.mock import MagicMock, patch

from plumbum import ProcessExecutionError
from plumbum.commands.processes import ProcessTimedOut

from vast_csi import filesystem_utils as fsu
from vast_csi.exceptions import MountFailed, UmountTimedOut


class MockConf:
    mount_umount_timeout = 30
    mock_vast = False


@pytest.fixture
def mock_conf():
    return MockConf()


def _mock_mount_cmd(mock_run):
    mock_mount_cmd = MagicMock()
    mock_mount_cmd.__getitem__ = MagicMock(return_value=mock_mount_cmd)
    mock_mount_cmd.__and__ = MagicMock(side_effect=lambda _: mock_run())
    return mock_mount_cmd


def _mock_umount_cmd(mock_run):
    mock_umount_cmd = MagicMock()
    mock_umount_cmd.__getitem__ = MagicMock(return_value=mock_umount_cmd)
    mock_umount_cmd.run = mock_run
    return mock_umount_cmd


class TestMount:
    def test_mount_success(self, mock_conf):
        mock_run = MagicMock(return_value=(0, "", ""))
        with (
            patch.object(fsu.cmd, "mount", _mock_mount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            fsu.mount("/dev/sda1", "/mnt/test", flags="ro,noexec", timeout=mock_conf.mount_umount_timeout)

            assert mock_log_info.call_count >= 2
            first_call = mock_log_info.call_args_list[0][0][0]
            assert "Mounting" in first_call
            assert "/dev/sda1" in first_call
            assert "/mnt/test" in first_call
            assert "timeout: 30s" in first_call
            last_call = mock_log_info.call_args_list[-1][0][0]
            assert "succeeded" in last_call

    def test_mount_timeout(self, mock_conf):
        with (
            patch.object(fsu, "run_with_timeout", side_effect=TimeoutError("timed out")),
            patch.object(fsu.logger, "info"),
        ):
            with pytest.raises(MountFailed) as exc_info:
                fsu.mount("/dev/sda1", "/mnt/test", timeout=mock_conf.mount_umount_timeout)

            assert "timed out" in exc_info.value.detail

    def test_mount_execution_error(self, mock_conf):
        mock_run = MagicMock(side_effect=ProcessExecutionError(
            argv=["mount"], retcode=1, stdout="",
            stderr="mount: /mnt/test: mount point does not exist",
        ))
        with (
            patch.object(fsu.cmd, "mount", _mock_mount_cmd(mock_run)),
            patch.object(fsu.logger, "info"),
        ):
            with pytest.raises(MountFailed) as exc_info:
                fsu.mount("/dev/sda1", "/mnt/test", timeout=mock_conf.mount_umount_timeout)

            assert "mount point does not exist" in exc_info.value.detail


class TestUmount:
    def test_umount_success(self, mock_conf):
        mock_run = MagicMock(return_value=(0, "", ""))
        with (
            patch.object(fsu.cmd, "umount", _mock_umount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            result = fsu.umount("/mnt/test", timeout=mock_conf.mount_umount_timeout)

            assert result is True
            assert mock_log_info.call_count >= 2
            first_call = mock_log_info.call_args_list[0][0][0]
            assert "Unmounting" in first_call
            assert "/mnt/test" in first_call
            last_call = mock_log_info.call_args_list[-1][0][0]
            assert "succeeded" in last_call

    def test_umount_timeout(self, mock_conf):
        with (
            patch.object(fsu, "run_with_timeout", side_effect=TimeoutError("timed out")),
            patch.object(fsu.logger, "info"),
        ):
            with pytest.raises(UmountTimedOut) as exc_info:
                fsu.umount("/mnt/test", timeout=mock_conf.mount_umount_timeout)

            assert "timed out" in str(exc_info.value)
            assert "30s" in str(exc_info.value)

    def test_umount_not_mounted_ignored(self, mock_conf):
        mock_run = MagicMock(side_effect=ProcessExecutionError(
            argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: not mounted",
        ))
        with (
            patch.object(fsu.cmd, "umount", _mock_umount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            result = fsu.umount("/mnt/test", ignore_not_mounted=True, timeout=mock_conf.mount_umount_timeout)

            assert result is False
            log_calls = [call[0][0] for call in mock_log_info.call_args_list]
            assert any("not mounted (ignored)" in call for call in log_calls)

    def test_umount_not_mounted_warning(self, mock_conf):
        mock_run = MagicMock(side_effect=ProcessExecutionError(
            argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: not mounted",
        ))
        with (
            patch.object(fsu.cmd, "umount", _mock_umount_cmd(mock_run)),
            patch.object(fsu.logger, "info"),
            patch.object(fsu.logger, "warning") as mock_log_warning,
        ):
            result = fsu.umount("/mnt/test", ignore_not_mounted=False, timeout=mock_conf.mount_umount_timeout)

            assert result is False
            assert mock_log_warning.call_count >= 1
            assert "not mounted" in mock_log_warning.call_args_list[0][0][0]

    def test_umount_other_error_raises(self, mock_conf):
        mock_run = MagicMock(side_effect=ProcessExecutionError(
            argv=["umount"], retcode=1, stdout="", stderr="umount: /mnt/test: device is busy",
        ))
        with (
            patch.object(fsu.cmd, "umount", _mock_umount_cmd(mock_run)),
            patch.object(fsu.logger, "info"),
        ):
            with pytest.raises(ProcessExecutionError):
                fsu.umount("/mnt/test", timeout=mock_conf.mount_umount_timeout)


class TestBlockMount:
    def test_mount_success_bind(self, mock_conf):
        mock_run = MagicMock(return_value=(0, "", ""))
        with (
            patch.object(fsu.cmd, "mount", _mock_mount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            fsu.mount("/dev/nvme0n1", "/mnt/test", bind=True, timeout=mock_conf.mount_umount_timeout)

            assert mock_log_info.call_count >= 2
            first_call = mock_log_info.call_args_list[0][0][0]
            assert "Mounting" in first_call
            assert "bind" in first_call

    def test_mount_success_with_fs_type(self, mock_conf):
        mock_run = MagicMock(return_value=(0, "", ""))
        with (
            patch.object(fsu.cmd, "mount", _mock_mount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            fsu.mount(
                "/dev/nvme0n1", "/mnt/test", fs_type="ext4", flags=["ro", "noexec"],
                timeout=mock_conf.mount_umount_timeout,
            )

            assert mock_log_info.call_count >= 2
            first_call = mock_log_info.call_args_list[0][0][0]
            assert "fs_type=ext4" in first_call
            assert "ro,noexec" in first_call

    def test_mount_timeout(self, mock_conf):
        with (
            patch.object(fsu, "run_with_timeout", side_effect=TimeoutError("timed out")),
            patch.object(fsu.logger, "info"),
        ):
            with pytest.raises(MountFailed) as exc_info:
                fsu.mount("/dev/nvme0n1", "/mnt/test", timeout=mock_conf.mount_umount_timeout)

            assert "timed out" in exc_info.value.detail


class TestPluginWrappers:
    """NFS/block wrappers pass CONF.mount_umount_timeout into filesystem_utils."""

    def test_nfs_mount_passes_timeout(self, mock_conf):
        with patch("vast_csi.plugins.nfs.CONF", mock_conf):
            from vast_csi.plugins import nfs

            with patch.object(nfs, "_mount") as mock_mount:
                nfs.mount("/src", "/tgt", flags="ro")
                mock_mount.assert_called_once_with(
                    "/src", "/tgt",
                    flags=["ro"],
                    metrics_registry=None,
                    metrics_operation="nfs",
                    timeout=30,
                )

    def test_block_mount_passes_timeout(self, mock_conf):
        with patch("vast_csi.plugins.block.CONF", mock_conf):
            from vast_csi.plugins import block

            with patch.object(block, "_mount") as mock_mount:
                block.mount("/dev/x", "/mnt", bind=True)
                mock_mount.assert_called_once_with(
                    "/dev/x", "/mnt",
                    flags=None, bind=True, fs_type=None,
                    metrics_registry=None, enforce_ro=False,
                    metrics_operation="block_mount",
                    timeout=30,
                )


class TestTimeoutConfiguration:
    def test_custom_timeout_value(self):
        with patch.object(fsu, "run_with_timeout") as mock_run_with_timeout:
            mock_run_with_timeout.side_effect = lambda func, timeout: func()
            with patch.object(fsu.cmd, "mount", _mock_mount_cmd(MagicMock(return_value=(0, "", "")))):
                with patch.object(fsu.logger, "info") as mock_log_info:
                    fsu.mount("/dev/sda1", "/mnt/test", timeout=60)

                    mock_run_with_timeout.assert_called_once()
                    assert mock_run_with_timeout.call_args[0][1] == 60
                    first_call = mock_log_info.call_args_list[0][0][0]
                    assert "timeout: 60s" in first_call


class TestDurationLogging:
    def test_mount_duration_logged(self, mock_conf):
        mock_run = MagicMock(return_value=(0, "", ""))
        with (
            patch.object(fsu.cmd, "mount", _mock_mount_cmd(mock_run)),
            patch.object(fsu.logger, "info") as mock_log_info,
        ):
            fsu.mount("/dev/sda1", "/mnt/test", timeout=mock_conf.mount_umount_timeout)

            last_call = mock_log_info.call_args_list[-1][0][0]
            assert "Mount succeeded" in last_call
            assert "/dev/sda1" in last_call and "/mnt/test" in last_call
