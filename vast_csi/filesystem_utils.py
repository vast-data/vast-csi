import os
import re
from shlex import split
from threading import RLock
from collections import defaultdict
from contextlib import contextmanager

from easypy.units import MINUTE
from requests.exceptions import HTTPError  # noqa
from plumbum import local, cmd, ProcessExecutionError
from plumbum.commands.processes import ProcessTimedOut
from vast_csi.logging import logger
from vast_csi.utils import run_with_timeout


PROC_MOUNT_INFO = "/proc/self/mountinfo"
# Regex for matching block device names typically used for CSI volumes.
# Supports:
# - NVMe devices (e.g., /nvme0n1 or nvme1n2)
DEVICE_NAME_RGX = re.compile(r"^/?nvme\d+n\d+$")


# Default formatting flags
# See https://github.com/kubernetes/mount-utils/blob/master/mount_linux.go#L592
MKFS_ARGS = {
    "ext4": [
        "-F",  # Force overwrite
        "-m0",  # Zero blocks reserved for super-user
    ],
    "ext3": [
        "-F",  # Force overwrite
        "-m0",  # Zero blocks reserved for super-user
    ],
    "xfs": [
        "-f",  # Force overwrite
        "-K",  # Skip discarding unused blocks (improves provisioning performance)
    ],
}


class HostCommand:
    """
    A utility for executing commands in the context of the Docker engine host's filesystem.
    This class uses a `chroot` environment to execute commands as if they were running directly
    on the Docker engine host. Commands are executed within a minimal environment to closely
    emulate the host system, ensuring compatibility and isolation.
    """
    HOST_MOUNT = local.path("/host")

    def __init__(self, base_cmd=None):
        self.base_cmd = base_cmd

    def __getattr__(self, item):
        """Dynamically sets the base command when accessing a non-existent attribute."""
        if not self.HOST_MOUNT.exists():
            raise Exception(f"Could not find Docker engine host's filesystem at expected location: {self.HOST_MOUNT}")
        self.base_cmd = item
        return self.__class__(base_cmd=item)

    def _get_cmd_chain(self, *args):
        assert self.base_cmd is not None, "Base command not set"
        return f"{self.base_cmd} {' '.join(map(str, args))}"

    def get_executable(self, *args):
        return cmd.bash[
            "-c", (
            f"exec chroot {self.HOST_MOUNT} /usr/bin/env -i "
            f"PATH=/sbin:/bin:/usr/bin:/usr/sbin {self._get_cmd_chain(*args)}"
            )
        ]

    def __call__(self, *args, timeout=None):
        """
        Executes the base command with the given arguments in the Docker host's chroot environment.
        Args:
            *args: Positional arguments to pass to the command.
            timeout (float or None, optional): Timeout for the command execution in seconds. Defaults to None.
        """

        def _execute_command():
            return self.get_executable(*args).run(retcode=None)

        if timeout is not None:
            try:
                retcode, stdout, stderr = run_with_timeout(_execute_command, timeout)
            except TimeoutError:
                cmd_str = self._get_cmd_chain(*args)
                raise ProcessTimedOut(f"Command timed out after {timeout}s: {cmd_str}", None)
        else:
            retcode, stdout, stderr = _execute_command()

        if retcode != 0:
            # Avoid using cmd.formulate() or any kind of cmd resolving within docker system context.
            # Because such commands as 'nvme' are available only on the host system.
            # .formulate causes 'which' execution which leads to AttributeError.
            raise ProcessExecutionError(
                retcode=retcode, stdout=stdout, stderr=stderr, argv=self._get_cmd_chain(*args).split()
            )
        return stdout


hostcmd = HostCommand()
realpath_cmd = HostCommand("realpath")

def get_host_realpath(path):
    """
    Get the real path of a given path in the Docker host's filesystem.
    This function uses the `realpath` command to resolve symbolic links and
    return the absolute path.
    """
    path = str(path)
    try:
        return realpath_cmd(path).strip()
    except ProcessExecutionError as exc:
        if "No such file or directory" in exc.stderr:
            # If the path doesn't exist, return the original path
            return path
        raise


class MountInfo:
    # Default BAD_MOUNTINFO tuple if there is insufficient data
    BAD_MOUNTINFO = ('', '', '', '', '', '', '-', '', '', '')

    def __init__(self, data):
        # Split the input data into a list
        data = data.split()

        length = len(data)
        # Validate the length of the data
        if length < 10:
            data = self.BAD_MOUNTINFO

        # Assign basic mount data fields
        self.mount_id = data[0]
        self.parent_id = data[1]
        self.st_dev = data[2]
        self.root = data[3]
        self.mount_point = data[4]
        self.mount_options = data[5]

        i = 6
        optional_fields = []
        while i < length and data[i] != '-':
            optional_fields.append(data[i])
            i += 1

        if i == length:
            data = self.BAD_MOUNTINFO
            i = 6

        self.optional_fields = optional_fields
        self.fs_type = data[i + 1]
        self.mount_source = data[i + 2]
        self.super_options = data[i + 3]

    @property
    def source(self):
        """Return the source of the mount, handling bind mounts."""
        if self.mount_source.startswith('/'):
            return self.mount_source
        return self.root

    @property
    def has_blockdev_root(self):
        """Return True if the root is a block device."""
        return bool(DEVICE_NAME_RGX.match(self.root))


    @property
    def block_device(self):
        """
        Return the device for a devtmpfs mount.
        The reason the device appears as /nvmexnx in the mount information even though it is mounted from /dev/nvmexnx
        is due to the way devtmpfs (Device Temporary File System) works and how devices are managed in the Linux kernel.
        """
        if self.has_blockdev_root:
            return os.path.join("/dev", self.root.lstrip("/"))
        raise ValueError(f"Expected blockdev mount, but found {self.root}.")

    @classmethod
    def from_host(cls):
        """Return a list of MountInfo objects from the host's mount info."""
        return [
            MountInfo(line) for line in hostcmd.cat(PROC_MOUNT_INFO).split("\n") if line
        ]

    @classmethod
    def get_mount_by_destination(cls, dest_path):
        """Return the source device for a path.
        The source of a mounted path will either be the mount source of the
        mount point or the root if it's a bind mount.
        This method  resolves symlinks to support real mounts.
        """
        dest_path_resolved = get_host_realpath(dest_path)
        mount_info = cls.from_host()
        for mount in mount_info:
            mount_point_resolved = get_host_realpath(mount.mount_point)
            if mount_point_resolved == dest_path_resolved:
                return mount
        return None

    @classmethod
    def get_mounts_by_source(cls, src):
        """
        Retrieve a list of mounts associated with a given source.
        This method behaves differently for bind mounts, depending
        on whether the source is a block device or a directory:
         - For bind mounts to block devices, the source is the block device itself.
           The search is performed by matching the device.
         - For bind mounts to directories, the source is the directory.
           The search establishes a relationship between the source and its mount point.
        Returns:
           A tuple containing:
           - The mount object corresponding to the given source, if found.
           - A list of target mounts associated with the source.
        """
        src_mount = None
        target_mounts = []
        src_resolved = get_host_realpath(src)

        mounts_by_source = defaultdict(list)
        mount_info = cls.from_host()

        for mount in mount_info:
            mount_point_resolved = get_host_realpath(mount.mount_point)
            mount_source_resolved = get_host_realpath(mount.source)

            if not src_mount and mount_point_resolved == src_resolved:
                src_mount = mount
            else:
                mounts_by_source[mount_source_resolved].append(mount)

        if src_mount:
            resolved_src = get_host_realpath(src_mount.source)
            resolved_mount_point = get_host_realpath(src_mount.mount_point)
            target_mounts = mounts_by_source[resolved_src] + mounts_by_source[resolved_mount_point]

        return src_mount, target_mounts


    def __str__(self):
        """String representation of the MountInfo object."""
        return f'<root: {self.root}, dest: {self.mount_point}, src: {self.mount_source}>'

    __repr__ = __str__


def get_filesystem_type(path: str):
    """Determine the filesystem type of given path using the `blkid` command."""
    retcode, stdout, stderr = cmd.blkid[path, "-s", "TYPE", "-o", "value"].run(retcode=None, timeout=10)
    if retcode not in (0, 2):
        # Disk device is unformatted.
        # For `blkid`, if the specified token (TYPE/PTTYPE, etc) was
        # not found, or no (specified) devices could be identified, an
        # exit code of 2 is returned.
        raise Exception(f"Failed to determine filesystem type for path '{path}': {stderr}")
    return stdout.strip() if retcode == 0 else None


def format_device(requested_fs: str, device: str, format_args: str = None):
    """
      Formats a given block device with the specified filesystem type.
      This function first checks the current filesystem on the device. If the device
      already has the requested filesystem, it does nothing. If the current filesystem
      is different from the requested one, it raises an exception. If no filesystem is
      present, it formats the device with the requested filesystem.
      Parameters:
      - requested_fs (str): The filesystem type to format the device with (e.g., 'ext4').
      - device (str): The block device to be formatted (e.g., '/dev/sda').
    """
    current_fs = get_filesystem_type(device)
    if current_fs == requested_fs:
        logger.info(f"Device {device} already has filesystem {requested_fs!r}")
        return False
    if current_fs:
        raise Exception(
            f"Cannot stage filesystem {requested_fs} on device that already has filesystem {current_fs}"
        )
    args = MKFS_ARGS.get(requested_fs, [])[:]
    if format_args:
        args += split(format_args)
    args.append(str(device))
    logger.info(f"{requested_fs} fs type has been requested with {args=}. Formatting device.")
    local[f"mkfs.{requested_fs}"][args] & logger.pipe_info(f"{requested_fs}: ", line_timeout=10 * MINUTE)
    return True


def get_device_size(device: str):
    """Get the size of the device using the 'blockdev' command."""
    output = cmd.blockdev("--getsize64", device).strip()
    try:
        return int(output)
    except ValueError:
        raise ValueError(f"Failed to parse size of device {device}: {output}")


def check_fs_integrity(device: str):
    """Check the integrity of the filesystem on the given device."""
    try:
        cmd.fsck["-a", "-f", device] & logger.pipe_info(f"fsck: ")
    except ProcessExecutionError as exc:
        # fsck returns 1 if it finds and fixes issues
        if exc.retcode == 1:
            logger.warning(f"fsck found and fixed issues on {device}: {exc}")
        else:
            raise


def get_fs_size(device: str, target_mount: str, fs_type: str):
    """Get the block size and filesystem size for all types filesystems."""
    if fs_type in ("ext3", "ext4"):
        return get_ext_size(device)
    elif fs_type == "xfs":
        return get_xfs_size(target_mount)
    else:
        raise Exception(
            f"Unsupported filesystem type {fs_type!r}."
            f" Supported fs types are: {', '.join(MKFS_ARGS)}"
        )


def ext_resize(device: str):
    """Resize ext3/ext4 filesystem."""
    cmd.resize2fs[device] & logger.pipe_info("resize2fs: ")
    logger.info(f"Device {device!r} resized successfully")


def xfs_resize(device: str):
    """Resize XFS filesystem."""
    cmd.xfs_growfs["-d", device] & logger.pipe_info("xfs_growfs: ")
    logger.info(f"Device {device!r} resized successfully")


def _parse_fs_info_output(
        output: str,
        delimiter: str,
        block_size_key: str,
        block_count_key: str,
):
    """Parse the output of the "fsinfo" command. "fsinfo" command is specific to ext and xfs filesystems."""
    block_size = block_count = 0
    for line in output.splitlines():
        tokens = line.split(delimiter)
        if len(tokens) != 2:
            continue
        key, value = tokens[0].strip().lower(), tokens[1].strip().lower()
        if key in block_size_key:
            block_size = int(value)
        elif key == block_count_key:
            block_count = int(value)
    return block_size, block_count

def get_ext_size(mount_path):
    """Get the size of ext filesystem."""
    output = cmd.dumpe2fs("-h", mount_path)
    block_size, block_count = _parse_fs_info_output(
        output=output, delimiter=":", block_size_key="block size", block_count_key="block count"
    )
    return block_size, block_size * block_count


def get_xfs_size(mount_path):
    """Get the size of xfs filesystem."""
    output = cmd.xfs_io("-c", "statfs", mount_path)
    block_size, block_count = _parse_fs_info_output(
        output=output, delimiter="=", block_size_key="geom.bsize", block_count_key="geom.datablocks")
    return block_size, block_size * block_count


def need_resize(device: str, target_mount, fs_type: str):
    """Determine if a device needs resizing."""
    if not fs_type:
        logger.info(f"need_resize - no filesystem type specified for device {device}")
        return

    device_size = get_device_size(device)
    block_size, fs_size = get_fs_size(device, target_mount, fs_type)
    if fs_size == 0:
        raise Exception(f"failed to read size of filesystem on device {device!r}")
    logger.info(
        f"device size={device_size}, filesystem size={fs_size}, block size={block_size}"
    )
    # Tolerate one block difference for rounding errors
    return device_size > fs_size + block_size


def resize_device(device: str, target_mount: str, fs_type: str):
    """Perform resize of the filesystem."""
    if need_resize(device, target_mount, fs_type):
        if fs_type in ("ext3", "ext4"):
            ext_resize(device)
        elif fs_type == "xfs":
            xfs_resize(target_mount)
        else:
            raise Exception(
                f"Unsupported filesystem type {fs_type!r}. Supported fs types are: ext3, ext4, xfs"
            )
    else:
        logger.info(f"Device {device!r} does not need resizing")


class VolumeLockedError(Exception):
    pass


@contextmanager
def volume_locked(volume_id, _locks=set(), _global_lock=RLock()):
    """helps ensure formatting/resizing of a volume does not happen concurrently"""
    with _global_lock:
        if volume_id in _locks:
            raise VolumeLockedError(f"Volume {volume_id} is locked")
        _locks.add(volume_id)
    try:
        yield
    finally:
        _locks.discard(volume_id)
