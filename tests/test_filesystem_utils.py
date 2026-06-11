import os.path
from threading import Thread, Event
from unittest.mock import MagicMock, patch, mock_open
import pytest
from pathlib import Path
from vast_csi.filesystem_utils import (
    MountInfo,
    hostcmd,
    resource_locked,
    ResourceLockedError,
    get_ext_size,
    get_xfs_size,
    mount,
    umount,
    temporary_mount,
    _normalize_mount_flags,
)
from vast_csi.exceptions import MountFailed, UmountTimedOut
from plumbum import cmd

PARENT = Path(__file__).parent.resolve()


@pytest.mark.host_only
def test_volume_stats_for_fs_type(*_):
    volume_path = "/var/lib/kubelet/pods/f2f1afd1-4afb-4eae-b57d-64672ee2811d/volumes/kubernetes.io~csi/pvc-9f3d8700-89be-49b5-b388-dc92f4c9e473/mount"
    mock_file_content = PARENT.joinpath("data/procmounts2").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        target_mount = MountInfo.get_mount_by_destination(dest_path=volume_path)
        assert target_mount.has_blockdev_root is False
        assert target_mount.root == "/"
        assert target_mount.mount_point == volume_path
        with pytest.raises(ValueError):
            target_mount.block_device


@pytest.mark.host_only
def test_volume_stats_for_block_type(*_):
    volume_path = "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/pvc-435b3f84-838e-4140-a4ec-f20bec791020/dev/9fbd20b4-90ee-43a7-ac5d-f3e3641e47d2"
    mock_file_content = PARENT.joinpath("data/procmounts2").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        target_mount = MountInfo.get_mount_by_destination(dest_path=volume_path)
        assert target_mount.has_blockdev_root is True
        assert target_mount.root == "/nvme1n1"
        assert target_mount.mount_point == volume_path
        assert target_mount.block_device == "/dev/nvme1n1"


@pytest.mark.host_only
def test_udev_managed_device(*_):
    device_bind_path = "/data/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/2cbfbe7c253f51c170b9299d79a2a73879b40ae4b50d9ea8f8fa98b7f27bc5f0/globalmount/device"
    mock_file_content = PARENT.joinpath("data/procmounts2").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        staging_mount = MountInfo.get_mount_by_destination(dest_path=device_bind_path)
        assert staging_mount
        device_path = staging_mount.block_device
        assert device_path == "/dev/nvme9n1"

@pytest.mark.host_only
def test_mount_info_block_staging_path(*_):
    device_bind_path = "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/staging/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/device"
    # 3 targets represents 3 PODS that are using the same PVC
    targets =  {
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/a247edfe-6bde-4926-b5a7-83c0f3cb5e5f",
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/fd7c2518-18da-44cb-8a1e-be2d331725c7",
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/73066e63-cb84-4d61-b1dc-6d3372ac9ae2",
    }
    mock_file_content = PARENT.joinpath("data/procmounts").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=device_bind_path)
        staging_mount2 = MountInfo.get_mount_by_destination(dest_path=device_bind_path)

    assert staging_mount
    assert staging_mount.mount_point == device_bind_path
    assert staging_mount2.mount_point == device_bind_path
    assert staging_mount.has_blockdev_root
    block_device = staging_mount.block_device
    assert block_device == "/dev/nvme1n1"
    # 3 mounts are binding from CSI driver and 3 are kubelet bindings
    assert len(target_mounts) == 6
    retrieved_targets = {target_mount.mount_point for target_mount in target_mounts}
    assert targets.issubset(retrieved_targets)


@pytest.mark.host_only
def test_mount_info_fs_staging_path(*_):
    device_bind_path = "/var/lib/kubelet/plugins/kubernetes.io/csi/pv/pvc-ccc37670-ad1c-4454-ab29-db35577b57f2/globalmount/device"
    targets = {
        "/var/lib/kubelet/pods/d518af61-36ab-4944-8125-937ddbd438e5/volumes/kubernetes.io~csi/pvc-ccc37670-ad1c-4454-ab29-db35577b57f2/mount",
        "/var/lib/kubelet/pods/7d0015d3-84a8-42e1-8211-5578f35c53db/volumes/kubernetes.io~csi/pvc-ccc37670-ad1c-4454-ab29-db35577b57f2/mount",
    }
    mock_file_content = PARENT.joinpath("data/procmounts").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=device_bind_path)
        staging_mount2 = MountInfo.get_mount_by_destination(dest_path=device_bind_path)

    assert staging_mount
    assert staging_mount.mount_point == device_bind_path
    assert staging_mount2.mount_point == device_bind_path

    assert staging_mount.has_blockdev_root
    block_device = staging_mount.block_device
    assert block_device == "/dev/nvme1n3"
    assert len(target_mounts) == 2
    retrieved_targets = {target_mount.mount_point for target_mount in target_mounts}
    assert targets.issubset(retrieved_targets)


@pytest.mark.host_only
def test_mount_info_ephemeral_staging_path(*_):
    """Test mount info with ephemeral kubelet path (e.g., /mnt/ephemeral/kubelet)."""
    device_bind_path = "/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/752b2142192f4c948dd1132c4f66f69388e2a188a6cfc6c4927bc55f840d16e0/globalmount/device"

    # Mock open() to return our test data (Ember-CSI approach: read /proc/self/mountinfo directly)
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=device_bind_path)
        staging_mount2 = MountInfo.get_mount_by_destination(dest_path=device_bind_path)

    assert staging_mount
    assert staging_mount.mount_point == device_bind_path
    assert staging_mount2 is not None
    assert staging_mount2.mount_point == device_bind_path

    assert staging_mount.has_blockdev_root
    block_device = staging_mount.block_device
    assert block_device == "/dev/nvme2n18"
    # This volume has no target mounts (not yet published to any pods)
    assert len(target_mounts) == 0


@pytest.mark.host_only
def test_mount_info_multiple_csi_devices(*_):
    """Test finding multiple CSI block devices in a large mount table."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    # Test multiple different CSI block device paths
    test_devices = [
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/5ac65567ffc4325f51d78ab2d444ef83bf0421342cc2c370f3c2d69c574a31da/globalmount/device", "/dev/nvme2n9"),
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/b49eccd2eda3adf7a40984545dda8a8387cd19e68053dff4d1c335d0b6f28773/globalmount/device", "/dev/nvme2n36"),
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/dbe7e33cb61cd7441c8b5b4fababc2be700aca0d8629c648dd1ee539d65d9ad9/globalmount/device", "/dev/nvme2n45"),
    ]

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        for device_path, expected_device in test_devices:
            mount = MountInfo.get_mount_by_destination(dest_path=device_path)
            assert mount is not None, f"Mount not found for {device_path}"
            assert mount.mount_point == device_path
            assert mount.has_blockdev_root
            assert mount.block_device == expected_device


@pytest.mark.host_only
def test_mount_info_non_existent_path(*_):
    """Test querying for a non-existent mount path returns None."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    non_existent_paths = [
        "/mnt/does/not/exist",
        "/var/lib/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/nonexistent/globalmount/device",
        "/mnt/ephemeral/kubelet/pods/fake-pod-id/volumes/kubernetes.io~csi/fake-volume/mount",
    ]

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        for path in non_existent_paths:
            mount = MountInfo.get_mount_by_destination(dest_path=path)
            assert mount is None, f"Expected None for non-existent path {path}, got {mount}"

            staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=path)
            assert staging_mount is None
            assert len(target_mounts) == 0


@pytest.mark.host_only
def test_mount_info_tmpfs_volumes(*_):
    """Test finding tmpfs empty-dir volumes among CSI mounts."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    # Test some tmpfs mounts used by Kubernetes empty-dir volumes
    tmpfs_mounts = [
        "/mnt/ephemeral/kubelet/pods/74f60506-233b-4a9a-a415-52e3ffc4a181/volumes/kubernetes.io~empty-dir/strimzi-tmp",
        "/mnt/ephemeral/kubelet/pods/9b4ef9d6-3f2e-47f1-bd3c-9c3a6591e179/volumes/kubernetes.io~empty-dir/strimzi-tmp",
        "/mnt/ephemeral/kubelet/pods/1c01af91-6dcb-4da6-b525-314f0a71c550/volumes/kubernetes.io~empty-dir/rack-volume",
    ]

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        for tmpfs_path in tmpfs_mounts:
            mount = MountInfo.get_mount_by_destination(dest_path=tmpfs_path)
            assert mount is not None, f"tmpfs mount not found: {tmpfs_path}"
            assert mount.mount_point == tmpfs_path
            assert mount.fs_type == "tmpfs"
            assert not mount.has_blockdev_root


@pytest.mark.host_only
def test_mount_info_large_mount_table_performance(*_):
    """Test that MountInfo can handle large mount tables efficiently (584 lines)."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        # Parse all mounts
        all_mounts = MountInfo.from_host()

        # Verify we got all mounts
        assert len(all_mounts) > 500, "Expected 500+ mounts in procmounts3"

        # Verify we can find CSI mounts efficiently
        csi_mounts = [m for m in all_mounts if "block.csi.vastdata.com" in m.mount_point]
        assert len(csi_mounts) > 30, "Expected 30+ CSI block mounts"

        # Verify all CSI mounts have block devices
        for csi_mount in csi_mounts:
            assert csi_mount.has_blockdev_root
            assert csi_mount.block_device.startswith("/dev/nvme2n")


@pytest.mark.host_only
def test_mount_info_various_nvme_devices(*_):
    """Test different NVMe device numbering (nvme2n1, nvme2n10, nvme2n87, etc.)."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    # Test devices with different numbering patterns
    test_cases = [
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/3e63644867658c026a7d2a091ff0716e07be68761912a0ffc43af2d32c70dcc2/globalmount/device", "nvme2n1"),
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/89fdcf67d178ba5d38dcb849e037568400a3edc2857b1bd4ba8e54be9d60d5c8/globalmount/device", "nvme2n10"),
        ("/mnt/ephemeral/kubelet/plugins/kubernetes.io/csi/block.csi.vastdata.com/a854f1fcdcb4a389a1ae198850e1ef5afa73c53d599b3b70c5ea9220ac2c9e6b/globalmount/device", "nvme2n87"),
    ]

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        for device_path, expected_nvme in test_cases:
            mount = MountInfo.get_mount_by_destination(dest_path=device_path)
            assert mount is not None
            assert mount.block_device == f"/dev/{expected_nvme}"
            assert mount.root == f"/{expected_nvme}"


@pytest.mark.host_only
def test_mount_info_system_mounts(*_):
    """Test finding standard system mounts in procmounts3."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    # Test some standard system mounts
    system_mounts = {
        "/dev": "devtmpfs",
        "/proc": "proc",
        "/sys": "sysfs",
        "/tmp": "tmpfs",
        "/": "ext4",
    }

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        for mount_point, expected_fstype in system_mounts.items():
            mount = MountInfo.get_mount_by_destination(dest_path=mount_point)
            assert mount is not None, f"System mount not found: {mount_point}"
            assert mount.fs_type == expected_fstype, f"Expected {expected_fstype} for {mount_point}, got {mount.fs_type}"


@pytest.mark.host_only
def test_mount_info_edge_case_similar_paths(*_):
    """Test distinguishing between similar mount paths."""
    mock_file_content = PARENT.joinpath("data/procmounts3").read_text()

    # These paths share prefixes but are different mounts
    similar_paths = [
        "/mnt/ephemeral/kubelet/pods/74f60506-233b-4a9a-a415-52e3ffc4a181/volumes/kubernetes.io~empty-dir/strimzi-tmp",
        "/mnt/ephemeral/kubelet/pods/74f60506-233b-4a9a-a415-52e3ffc4a181/volumes/kubernetes.io~empty-dir/rack-volume",
        "/mnt/ephemeral/kubelet/pods/74f60506-233b-4a9a-a415-52e3ffc4a181/volumes/kubernetes.io~empty-dir/ready-files",
    ]

    with patch("builtins.open", mock_open(read_data=mock_file_content)):
        mounts = {}
        for path in similar_paths:
            mount = MountInfo.get_mount_by_destination(dest_path=path)
            assert mount is not None, f"Mount not found: {path}"
            mounts[path] = mount

        # Verify each mount is distinct
        assert len(set(m.mount_id for m in mounts.values())) == len(similar_paths)

        # Verify each has correct mount point
        for path, mount in mounts.items():
            assert mount.mount_point == path


def test_resource_locked():
    volume_id = "vol-1234"
    lock_acquired = Event()
    lock_released = Event()

    def lock_volume():
        with resource_locked(volume_id):
            lock_acquired.set()
            lock_released.wait()

    thread = Thread(target=lock_volume)
    thread.start()
    assert lock_acquired.wait(timeout=5), "Thread did not acquire the lock in time"

    # Try to acquire the lock in the main thread, which should raise an error
    with pytest.raises(ResourceLockedError):
        with resource_locked(volume_id):
            pass

    lock_released.set()
    thread.join()

    with resource_locked(volume_id):
        pass


dumpe2fs_out = """
Filesystem volume name:
Last mounted on:          /
Filesystem UUID:          bb29dda3-bdaa-4b39-86cf-4a6dc9634a1b
Filesystem magic number:  0xEF53
Filesystem revision #:    1 (dynamic)
Filesystem features:      has_journal ext_attr resize_inode dir_index filetype needs_recovery extent flex_bg sparse_super large_file huge_file uninit_bg dir_nlink extra_isize
Filesystem flags:         signed_directory_hash
Default mount options:    user_xattr acl
Filesystem state:         clean
Errors behavior:          Continue
Filesystem OS type:       Linux
Inode count:              21544960
Block count:              86154752
Reserved block count:     4307737
Free blocks:              22387732
Free inodes:              21026406
First block:              0
Block size:               4096
Fragment size:            4096
Reserved GDT blocks:      1003
Blocks per group:         32768
Fragments per group:      32768
Inodes per group:         8192
Inode blocks per group:   512
Flex block group size:    16
Filesystem created:       Sun Jul 31 16:19:36 2016
Last mount time:          Mon Nov  6 10:25:28 2017
Last write time:          Mon Nov  6 10:25:19 2017
Mount count:              432
Maximum mount count:      -1
Last checked:             Sun Jul 31 16:19:36 2016
Check interval:           0 ()
Lifetime writes:          2834 GB
Reserved blocks uid:      0 (user root)
Reserved blocks gid:      0 (group root)
First inode:              11
Inode size:	          256
Required extra isize:     28
Desired extra isize:      28
Journal inode:            8
First orphan inode:       6947324
Default directory hash:   half_md4
Directory Hash Seed:      9da5dafb-bded-494d-ba7f-5c0ff3d9b805
Journal backup:           inode blocks
Journal features:         journal_incompat_revoke
Journal size:             128M
Journal length:           32768
Journal sequence:         0x00580f0c
Journal start:            12055
"""


@patch.object(cmd, "dumpe2fs", return_value=dumpe2fs_out)
def test_parse_ext_output(*_):
    block_size, fs_size = get_ext_size("/dev/nvme1n1")

    # Assertions
    assert block_size == 4096
    assert fs_size == 352889864192


xfs_info_out = """
fd.path = "/var/lib/kubelet/pods/48541017-9bf2-4aa3-9fd0-1122aecdebef/volumes/kubernetes.io~csi/pvc-57e1fee1-a72a-4224-a1e8-04de830aa2ae/mount"
statfs.f_bsize = 4096
statfs.f_blocks = 2605056
statfs.f_bavail = 2578630
statfs.f_files = 5242880
statfs.f_ffree = 5242877
statfs.f_flags = 0x1020
geom.bsize = 4096
geom.agcount = 4
geom.agblocks = 655360
geom.datablocks = 2621440
geom.rtblocks = 0
geom.rtextents = 0
geom.rtextsize = 1
geom.sunit = 0
geom.swidth = 0
counts.freedata = 2578630
counts.freertx = 0
counts.freeino = 61
counts.allocino = 64
"""

@patch.object(cmd, "xfs_io", return_value=xfs_info_out)
def test_parse_xfs_output(*_):
    block_size, fs_size = get_xfs_size("/test/mnt")

    # Assertions
    assert block_size == 4096
    assert fs_size == 10737418240


def _mock_plumbum_cmd():
    """Chainable mock for plumbum cmd.mount / cmd.umount."""
    mock_cmd = MagicMock()
    mock_cmd.__getitem__ = MagicMock(return_value=mock_cmd)
    return mock_cmd


class TestNormalizeMountFlags:
    def test_none_and_empty(self):
        assert _normalize_mount_flags(None) == []
        assert _normalize_mount_flags([]) == []

    def test_string_split(self):
        assert _normalize_mount_flags("ro,noexec") == ["ro", "noexec"]

    def test_list_passthrough(self):
        assert _normalize_mount_flags(["nouuid", "ro"]) == ["nouuid", "ro"]


class TestFilesystemUtilsMount:
    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_mount_fs_type_uses_run_with_timeout(self, mock_run_with_timeout):
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()
        mock_mount_cmd = _mock_plumbum_cmd()

        with patch.object(cmd, "mount", mock_mount_cmd):
            mount("/dev/nvme0n1", "/mnt/probe", fs_type="xfs", flags=["nouuid", "ro"], timeout=30)

        mock_run_with_timeout.assert_called_once()
        assert mock_run_with_timeout.call_args[0][1] == 30

    @patch("vast_csi.filesystem_utils.run_with_timeout", side_effect=TimeoutError("timed out"))
    def test_mount_timeout_raises_mount_failed(self, _mock_run_with_timeout):
        with patch.object(cmd, "mount", _mock_plumbum_cmd()):
            with pytest.raises(MountFailed) as exc_info:
                mount("/dev/nvme0n1", "/mnt/probe", fs_type="xfs", timeout=5)

        assert "timed out after 5s" in exc_info.value.detail

    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_mount_execution_error_raises_mount_failed(self, mock_run_with_timeout):
        from plumbum import ProcessExecutionError

        mock_mount_cmd = _mock_plumbum_cmd()
        mock_mount_cmd.__and__ = MagicMock(side_effect=ProcessExecutionError(
            ["mount"], 1, "", "mount: bad superblock"
        ))
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()

        with patch.object(cmd, "mount", mock_mount_cmd):
            with pytest.raises(MountFailed) as exc_info:
                mount("/dev/nvme0n1", "/mnt/probe", fs_type="xfs", timeout=10)

        assert "bad superblock" in exc_info.value.detail

    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_mount_bind_enforce_ro_remounts(self, mock_run_with_timeout):
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()
        mock_mount_cmd = _mock_plumbum_cmd()

        with patch.object(cmd, "mount", mock_mount_cmd):
            mount("/dev/nvme0n1", "/staging/device", bind=True, enforce_ro=True, timeout=15)

        assert mock_mount_cmd.__and__.call_count == 2

    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_mount_without_timeout_runs_directly(self, mock_run_with_timeout):
        mock_mount_cmd = _mock_plumbum_cmd()

        with patch.object(cmd, "mount", mock_mount_cmd):
            mount("server:/export", "/mnt/nfs", flags="vers=3")

        mock_run_with_timeout.assert_not_called()
        assert mock_mount_cmd.__and__.called


class TestFilesystemUtilsUmount:
    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_umount_success(self, mock_run_with_timeout):
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()
        mock_umount_cmd = _mock_plumbum_cmd()

        with patch.object(cmd, "umount", mock_umount_cmd):
            assert umount("/mnt/test", timeout=20) is True

        mock_run_with_timeout.assert_called_once()
        assert mock_run_with_timeout.call_args[0][1] == 20

    @patch("vast_csi.filesystem_utils.run_with_timeout", side_effect=TimeoutError("timed out"))
    def test_umount_timeout_raises(self, _mock_run_with_timeout):
        with patch.object(cmd, "umount", _mock_plumbum_cmd()):
            with pytest.raises(UmountTimedOut) as exc_info:
                umount("/mnt/test", timeout=12)

        assert "12s" in str(exc_info.value)

    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_umount_not_mounted_ignored(self, mock_run_with_timeout):
        from plumbum import ProcessExecutionError

        mock_umount_cmd = _mock_plumbum_cmd()
        mock_umount_cmd.run.side_effect = ProcessExecutionError(
            ["umount"], 1, "", "umount: /mnt/test: not mounted"
        )
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()

        with patch.object(cmd, "umount", mock_umount_cmd):
            assert umount("/mnt/test", ignore_not_mounted=True, timeout=10) is False

    @patch("vast_csi.filesystem_utils.run_with_timeout")
    def test_umount_lazy_flag(self, mock_run_with_timeout):
        index_args = []
        mock_umount_cmd = _mock_plumbum_cmd()
        mock_umount_cmd.__getitem__.side_effect = lambda key: (
            index_args.append(key) or mock_umount_cmd
        )
        mock_run_with_timeout.side_effect = lambda func, _timeout: func()

        with patch.object(cmd, "umount", mock_umount_cmd):
            umount("/mnt/test", lazy=True, timeout=10)

        assert ["-v", "-l", "/mnt/test"] in index_args


class TestTemporaryMount:
    @patch("vast_csi.filesystem_utils.umount")
    @patch("vast_csi.filesystem_utils.mount")
    @patch("vast_csi.filesystem_utils.TemporaryDirectory")
    def test_temporary_mount_xfs(self, mock_td, mock_mount, mock_umount):
        mock_td.return_value.__enter__.return_value = "/tmp/vast-csi-temp"

        with temporary_mount("/dev/nvme0n1", "/staging", "xfs", readonly=True, timeout=30):
            pass

        mock_mount.assert_called_once_with(
            src="/dev/nvme0n1",
            tgt="/tmp/vast-csi-temp",
            bind=False,
            fs_type="xfs",
            flags=["nouuid", "ro"],
            timeout=30,
        )
        mock_umount.assert_called_once_with(
            "/tmp/vast-csi-temp",
            ignore_not_mounted=True,
            timeout=30,
        )

    @patch("vast_csi.filesystem_utils.umount")
    @patch("vast_csi.filesystem_utils.mount")
    @patch("vast_csi.filesystem_utils.TemporaryDirectory")
    @patch("builtins.open", new_callable=mock_open)
    def test_temporary_mount_ext4_bind(self, _mock_file_open, mock_td, mock_mount, mock_umount):
        mock_td.return_value.__enter__.return_value = "/tmp/vast-csi-temp"

        with temporary_mount("/dev/nvme0n1", "/staging", "ext4", timeout=15):
            pass

        mock_mount.assert_called_once()
        kwargs = mock_mount.call_args[1]
        assert kwargs["bind"] is True
        assert kwargs["fs_type"] is None
        assert kwargs["tgt"].endswith("/device")
        mock_umount.assert_called_once_with(
            kwargs["tgt"],
            ignore_not_mounted=True,
            timeout=15,
        )
