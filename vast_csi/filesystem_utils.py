import os
from shlex import split
from collections import defaultdict
from requests.exceptions import HTTPError  # noqa
from plumbum import local, cmd, ProcessExecutionError
from vast_csi.logging import logger


PROC_MOUNT_INFO = "/proc/self/mountinfo"

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
        executable = self.get_executable(*args)
        retcode, stdout, stderr = executable.run(retcode=None, timeout=timeout)
        if retcode != 0:
            # Avoid using cmd.formulate() or any kind of cmd resolving within docker system context.
            # Because such commands as 'nvme' are available only on the host system.
            # .formulate causes 'which' execution which leads to AttributeError.
            raise ProcessExecutionError(
                retcode=retcode, stdout=stdout, stderr=stderr, argv=self._get_cmd_chain(*args).split()
            )
        return stdout


hostcmd = HostCommand()


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
    def has_devtmpfs_source(self):
        """Return True if the mount source is a block device."""
        return self.mount_source.startswith("devtmpfs")

    @property
    def devtmpfs_device(self):
        """
        Return the device for a devtmpfs mount.
        The reason the device appears as /nvmexnx in the mount information even though it is mounted from /dev/nvmexnx
        is due to the way devtmpfs (Device Temporary File System) works and how devices are managed in the Linux kernel.
        """
        if self.has_devtmpfs_source:
            return os.path.join("/dev", self.root.lstrip("/"))
        raise ValueError(f"Expected devtmpfs mount, but found {self.mount_source}.")

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
        """
        mount_info = cls.from_host()
        for mount in mount_info:
            if mount.mount_point == str(dest_path):
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
        mounts_by_source = defaultdict(list)
        mount_info = cls.from_host()
        for mount in mount_info:
            if not src_mount and mount.mount_point == str(src):
                src_mount = mount
            else:
                mounts_by_source[mount.source].append(mount)
        if src_mount:
            target_mounts = mounts_by_source[src_mount.source] + mounts_by_source[src_mount.mount_point]
        return src_mount, target_mounts


    def __str__(self):
        """String representation of the MountInfo object."""
        return f'<root: {self.root}, dest: {self.mount_point}, src: {self.mount_source}>'

    __repr__ = __str__


def get_filesystem_type(path: str):
    """Determine the filesystem type of given path using the `blkid` command."""
    retcode, stdout, stderr = cmd.blkid[path, "-s", "TYPE", "-o", "value"].run(retcode=None)
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
        return
    if current_fs:
        raise Exception(
            f"Cannot stage filesystem {requested_fs} on device that already has filesystem {current_fs}"
        )
    args = MKFS_ARGS.get(requested_fs, [])[:]
    if format_args:
        args += split(format_args)
    args.append(str(device))
    logger.info(f"{requested_fs} fs type has been requested with {args=}. Formatting device.")
    local[f"mkfs.{requested_fs}"][args] & logger.pipe_info(f"{requested_fs}: ")



class FsFormatterLockError(Exception):
    pass

class FsFormatter:
    """
    A class to manage the formatting of block devices with filesystem types while ensuring
    that concurrent formatting operations on the same volume are prevented.
    """

    locks = set()

    @classmethod
    def format_device(cls, volume_id: str, requested_fs: str, device: str, format_args: str = None):
        if cls.id_exists(volume_id):
            raise FsFormatterLockError(f"Volume {volume_id} is already being formatted")
        cls.locks.add(volume_id)
        try:
            format_device(requested_fs, device, format_args)
        finally:
            cls.locks.discard(volume_id)

    @classmethod
    def id_exists(cls, volume_id):
        return volume_id in cls.locks
