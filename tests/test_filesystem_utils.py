from threading import Thread, Event
from unittest.mock import patch
import pytest
from pathlib import Path
from vast_csi.filesystem_utils import (
    MountInfo,
    hostcmd,
    volume_locked,
    VolumeLockedError,
    get_ext_size,
    get_xfs_size,
)
from plumbum import cmd

PARENT = Path(__file__).parent.resolve()


@pytest.mark.host_only
def test_mount_info_block_staging_path(*_):
    device_bind_path = "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/staging/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/device"
    # 3 targets represents 3 PODS that are using the same PVC
    targets =  {
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/a247edfe-6bde-4926-b5a7-83c0f3cb5e5f",
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/fd7c2518-18da-44cb-8a1e-be2d331725c7",
        "/var/lib/kubelet/plugins/kubernetes.io/csi/volumeDevices/publish/pvc-590c142c-ae3c-46f3-894e-fdedb627d64f/73066e63-cb84-4d61-b1dc-6d3372ac9ae2",
    }

    with patch.object(hostcmd, "cat", return_value=PARENT.joinpath("data/procmounts").read_text()):
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=device_bind_path)
        staging_mount2 = MountInfo.get_mount_by_destination(dest_path=device_bind_path)

    assert staging_mount
    assert staging_mount.mount_point == device_bind_path
    assert staging_mount2.mount_point == device_bind_path

    assert staging_mount.has_devtmpfs_source
    devtmpfs_device = staging_mount.devtmpfs_device
    assert devtmpfs_device == "/dev/nvme1n1"
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

    with patch.object(hostcmd, "cat", return_value=PARENT.joinpath("data/procmounts").read_text()):
        staging_mount, target_mounts = MountInfo.get_mounts_by_source(src=device_bind_path)
        staging_mount2 = MountInfo.get_mount_by_destination(dest_path=device_bind_path)

    assert staging_mount
    assert staging_mount.mount_point == device_bind_path
    assert staging_mount2.mount_point == device_bind_path

    assert staging_mount.has_devtmpfs_source
    devtmpfs_device = staging_mount.devtmpfs_device
    assert devtmpfs_device == "/dev/nvme1n3"
    assert len(target_mounts) == 2
    retrieved_targets = {target_mount.mount_point for target_mount in target_mounts}
    assert targets.issubset(retrieved_targets)


def test_volume_locked():
    volume_id = "vol-1234"
    lock_acquired = Event()
    lock_released = Event()

    def lock_volume():
        with volume_locked(volume_id):
            lock_acquired.set()
            lock_released.wait()

    thread = Thread(target=lock_volume)
    thread.start()
    assert lock_acquired.wait(timeout=5), "Thread did not acquire the lock in time"

    # Try to acquire the lock in the main thread, which should raise an error
    with pytest.raises(VolumeLockedError):
        with volume_locked(volume_id):
            pass

    lock_released.set()
    thread.join()

    with volume_locked(volume_id):
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
