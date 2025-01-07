from unittest.mock import patch
import pytest
from pathlib import Path
from vast_csi.filesystem_utils import  MountInfo, hostcmd

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
