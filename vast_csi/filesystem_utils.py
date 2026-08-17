import os
import re
import tempfile
from shlex import split
from threading import RLock
from collections import defaultdict
from contextlib import contextmanager, nullcontext
from tempfile import TemporaryDirectory

from easypy.units import MINUTE
from easypy.timing import timing
from requests.exceptions import HTTPError  # noqa
from plumbum import local, cmd, ProcessExecutionError, FG
from plumbum.commands.processes import ProcessTimedOut
from vast_csi.logging import logger
from vast_csi.exceptions import Abort, FilesystemIntegrityError, MountFailed, UmountTimedOut
from vast_csi import csi_types as types
from vast_csi.utils import run_with_timeout


PROC_MOUNT_INFO = "/proc/self/mountinfo"
XFS_DB_TIMEOUT = 30
# Regex for matching block device names typically used for CSI volumes.
# Supports:
# - NVMe devices (e.g., /nvme0n1 or nvme1n2)
DEVICE_NAME_RGX = re.compile(r"^/?nvme\d+n\d+$")

# Cap for the meta overlay tmpfs written before the volume mount.
# Holds a single .vast-csi-meta JSON file (volume id plus optional AES-GCM
# encrypted VMS session / LUKS manager). Typical payload is a few KB even
# with a PEM cert; 64K covers that after page-size rounding (4K x86 / 64K ARM).
META_TMPFS_SIZE = "64K"

DEFAULT_HOST_BINARY_DIRS = (
    "/usr/sbin",
    "/usr/bin",
    "/sbin",
    "/bin",
    "/usr/local/sbin",
    "/usr/local/bin",
)


def parse_host_binary_search_dirs(raw: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    """Parse comma-separated host directory paths; empty raw => defaults only."""
    if not raw.strip():
        return defaults
    extra = []
    for item in raw.split(","):
        path = item.strip().rstrip("/")
        if not path:
            continue
        if not path.startswith("/"):
            raise ValueError(f"host binary search dir must be absolute: {path!r}")
        extra.append(path)
    if not extra:
        return defaults
    seen = set()
    merged = []
    for path in (*defaults, *extra):
        if path not in seen:
            seen.add(path)
            merged.append(path)
    return tuple(merged)


def resolve_host_binary_path(
    candidate_paths: tuple[str, ...],
    host_mount=None,
) -> str | None:
    if host_mount is None:
        host_mount = HostCommandAdapter.HOST_MOUNT
    if not host_mount.exists():
        return None

    host_root = os.path.realpath(str(host_mount))
    for host_path in candidate_paths:
        candidate = host_mount / host_path.lstrip("/")
        if not candidate.exists():
            continue
        real = os.path.realpath(str(candidate))
        if not (real == host_root or real.startswith(host_root + os.sep)):
            continue
        if os.access(real, os.X_OK):
            return "/" + os.path.relpath(real, host_root)
    return None


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


def run_executable(
    executable,
    *,
    argv: list[str],
    timeout=None,
    pipe: bool = False,
    pipe_prefix: str | None = None,
    fg: bool = False,
    thread_timeout: bool = False,
) -> str:
    """Run a plumbum executable; raise on non-zero exit or timeout."""
    cmd_line = " ".join(argv)
    try:
        if fg:
            executable & FG
            return ""
        if pipe:
            prefix = pipe_prefix if pipe_prefix is not None else f"{argv[0]}: "
            retcode, stdout, stderr = executable.run(retcode=None, timeout=timeout)
            for line in stdout.splitlines():
                logger.info("%s%s", prefix, line)
            for line in stderr.splitlines():
                logger.info("%s%s", prefix, line)
        else:

            def _run():
                return executable.run(retcode=None)

            if timeout is not None and thread_timeout:
                try:
                    retcode, stdout, stderr = run_with_timeout(_run, timeout)
                except TimeoutError:
                    raise ProcessTimedOut(
                        f"Command timed out after {timeout}s: {cmd_line}", None
                    )
            elif timeout is not None:
                retcode, stdout, stderr = executable.run(retcode=None, timeout=timeout)
            else:
                retcode, stdout, stderr = _run()
    except ProcessTimedOut:
        raise ProcessTimedOut(
            f"Command timed out after {timeout}s: {cmd_line}", None
        )

    if retcode != 0:
        raise ProcessExecutionError(
            retcode=retcode, stdout=stdout, stderr=stderr, argv=argv
        )
    return stdout


class HostToolRunner:
    """Callable runner for one host binary via chroot to a resolved absolute path."""

    def __init__(
        self,
        adapter: "HostCommandAdapter",
        tool: str,
        *,
        pipe_prefix: str | None = None,
        not_found_hint: str = "",
    ):
        self._adapter = adapter
        self._tool = tool
        self._pipe_prefix = pipe_prefix if pipe_prefix is not None else f"{tool}: "
        self._not_found_hint = not_found_hint

    def resolve_path(self) -> str:
        return self._adapter._resolve_tool(
            self._tool,
            self._adapter.candidate_paths_for(self._tool),
            not_found_hint=self._not_found_hint,
        )

    def get_executable(self, *args):
        return cmd.chroot[
            str(self._adapter.HOST_MOUNT), self.resolve_path(), *map(str, args)
        ]

    def __call__(self, *args, timeout=None, pipe=False, stdin=None, fg=False):
        executable = self.get_executable(*args)
        if stdin is not None:
            executable = cmd.echo["-n", stdin] | executable
        return run_executable(
            executable,
            argv=[self._tool, *map(str, args)],
            timeout=timeout,
            pipe=pipe,
            pipe_prefix=self._pipe_prefix,
            fg=fg,
            thread_timeout=timeout is not None and not pipe,
        )


class HostCommandAdapter:
    """
  Execute utilities on the Docker/Kubernetes node host via chroot into /host.

  Resolves each tool once by scanning configured base directories (defaults cover
  common Linux layouts). Resolved paths are memoized per tool. Commands use
  chroot to the absolute binary path so host /usr/bin/env is not required
  (Talos and other minimal nodes).
    """

    HOST_MOUNT = local.path("/host")

    def __init__(self):
        self._lock = RLock()
        self._resolved: dict[str, str] = {}
        self._resolved_for: dict[str, tuple[str, ...]] = {}
        self._runners: dict[str, HostToolRunner] = {}

    def search_dirs(self) -> tuple[str, ...]:
        from vast_csi.configuration import Config

        return parse_host_binary_search_dirs(
            Config().block_host_binary_search_dirs,
            DEFAULT_HOST_BINARY_DIRS,
        )

    def candidate_paths_for(self, tool: str) -> tuple[str, ...]:
        dirs = self.search_dirs()
        return tuple(f"{d}/{tool}" for d in dirs)

    def _resolve_tool(
        self,
        tool: str,
        candidates: tuple[str, ...],
        *,
        not_found_hint: str = "",
    ) -> str:
        with self._lock:
            if self._resolved.get(tool) and self._resolved_for.get(tool) == candidates:
                return self._resolved[tool]

        if not self.HOST_MOUNT.exists():
            raise ProcessExecutionError(
                retcode=127,
                stdout="",
                stderr=f"host root not mounted at {self.HOST_MOUNT}",
                argv=[tool],
            )

        resolved = resolve_host_binary_path(candidates, self.HOST_MOUNT)
        if resolved is None:
            hint = f". {not_found_hint}" if not_found_hint else ""
            raise ProcessExecutionError(
                retcode=127,
                stdout="",
                stderr=f"host {tool} not found; searched: {', '.join(candidates)}{hint}",
                argv=[tool],
            )

        with self._lock:
            self._resolved[tool] = resolved
            self._resolved_for[tool] = candidates
        logger.info("host %s: using %s", tool, resolved)
        return resolved

    def reset_cache(self, tool: str | None = None) -> None:
        with self._lock:
            if tool is None:
                self._resolved.clear()
                self._resolved_for.clear()
            else:
                self._resolved.pop(tool, None)
                self._resolved_for.pop(tool, None)

    def tool(
        self,
        name: str,
        *,
        pipe_prefix: str | None = None,
        not_found_hint: str = "",
    ) -> HostToolRunner:
        key = (name, pipe_prefix, not_found_hint)
        if key not in self._runners:
            self._runners[key] = HostToolRunner(
                self,
                name,
                pipe_prefix=pipe_prefix,
                not_found_hint=not_found_hint,
            )
        return self._runners[key]

    def __getattr__(self, item: str) -> HostToolRunner:
        if item.startswith("_"):
            raise AttributeError(item)
        return self.tool(item)


host_commands = HostCommandAdapter()
hostnvme = host_commands.tool(
    "nvme",
    not_found_hint="Install nvme-cli on the node (Talos: nvme-cli system extension).",
    pipe_prefix="nvme: ",
)
realpath_cmd = host_commands.realpath

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
            logger.warning(f"{path} doesn't exist")
        else:
            # e.g. "Input/output error" from a corrupted/stale mount — log and
            # fall back to the unresolved path so callers can skip this entry.
            logger.warning(f"realpath {path} failed: {exc.stderr.strip()}")
        return path


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
    def server_ip(self):
        """Return the server IP for NFS mounts (e.g. '172.21.112.4' from '172.21.112.4:/path')."""
        if ":" in self.mount_source:
            return self.mount_source.split(":", 1)[0]
        return None

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
        """
        Return a list of MountInfo objects from the host's mount info.
        Host mounts are visible due to mountPropagation: Bidirectional on /var/lib/kubelet.
        """
        with open(PROC_MOUNT_INFO) as f:
            return [MountInfo(line) for line in f if line.strip()]

    @classmethod
    def _mount_at_destination(cls, dest_path, resolve_symlink=False, fstypes=None, skip_fstypes=None):
        dest_path_resolved = get_host_realpath(dest_path) if resolve_symlink else dest_path
        allow = set(fstypes) if fstypes else None
        skip = set(skip_fstypes or ())
        found = None
        for mount in cls.from_host():
            if allow is not None and mount.fs_type not in allow:
                continue
            if mount.fs_type in skip:
                continue
            mount_point_resolved = get_host_realpath(mount.mount_point) if resolve_symlink else mount.mount_point
            if mount_point_resolved == dest_path_resolved:
                found = mount
        return found

    @classmethod
    def get_mount_by_destination(cls, dest_path, resolve_symlink=False):
        """Return the topmost mount for a path (any fstype, including tmpfs)."""
        return cls._mount_at_destination(dest_path, resolve_symlink=resolve_symlink)

    @classmethod
    def get_volume_mount_by_destination(cls, dest_path, resolve_symlink=False):
        """Published volume at dest_path. Never the tmpfs meta overlay."""
        return cls._mount_at_destination(
            dest_path, resolve_symlink=resolve_symlink, skip_fstypes=("tmpfs",)
        )

    @classmethod
    def get_tmpfs_mount_by_destination(cls, dest_path, resolve_symlink=False):
        """Meta-overlay tmpfs at dest_path. Never the published volume."""
        return cls._mount_at_destination(
            dest_path, resolve_symlink=resolve_symlink, fstypes=("tmpfs",)
        )

    @classmethod
    def get_mounts_by_source(cls, src, resolve_symlink=False):
        """
        Retrieve a list of mounts associated with a given source.
        This method behaves differently for bind mounts, depending
        on whether the source is a block device or a directory:
         - For bind mounts to block devices, the source is the block device itself.
           The search is performed by matching the device.
         - For bind mounts to directories, the source is the directory.
           The search establishes a relationship between the source and its mount point.
        
        Args:
            src: Source path to search for
            resolve_symlink: If True, resolve symlinks via get_host_realpath (slower).
                           If False (default), use paths as-is for better performance.
        
        Returns:
           A tuple containing:
           - The mount object corresponding to the given source, if found.
           - A list of target mounts associated with the source.
        """
        src_mount = None
        target_mounts = []
        src_resolved = get_host_realpath(src) if resolve_symlink else src

        mounts_by_source = defaultdict(list)
        mount_info = cls.from_host()

        for mount in mount_info:
            mount_point_resolved = get_host_realpath(mount.mount_point) if resolve_symlink else mount.mount_point
            mount_source_resolved = get_host_realpath(mount.source) if resolve_symlink else mount.source

            if not src_mount and mount_point_resolved == src_resolved:
                src_mount = mount
            else:
                mounts_by_source[mount_source_resolved].append(mount)

        if src_mount:
            resolved_src = get_host_realpath(src_mount.source) if resolve_symlink else src_mount.source
            resolved_mount_point = get_host_realpath(src_mount.mount_point) if resolve_symlink else src_mount.mount_point
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


def _normalize_mount_flags(flags):
    if not flags:
        return []
    if isinstance(flags, str):
        return [f.strip() for f in flags.split(",") if f.strip()]
    return list(flags)


def mount(
    src,
    tgt,
    flags=None,
    bind=False,
    fs_type=None,
    enforce_ro=False,
    metrics_registry=None,
    metrics_operation="block_mount",
    timeout=None,
):
    """
    Mount a path with optional timeout via run_with_timeout (avoids hung mount on I/O issues).

    Used by block (bind / filesystem), NFS, staging probes, and temporary_mount.
    """
    flags = _normalize_mount_flags(flags)
    if enforce_ro and "ro" not in flags:
        flags.append("ro")

    need_ro_remount = enforce_ro and bind

    if bind:
        bind_flags = [f for f in flags if f != "ro"]
        executable = cmd.mount["--bind"]
        if bind_flags:
            executable = executable["-o", ",".join(bind_flags)]
    elif fs_type:
        executable = cmd.mount["-t", fs_type]
        if flags:
            executable = executable["-o", ",".join(flags)]
    else:
        executable = cmd.mount
        if flags:
            executable = executable["-o", ",".join(flags)]

    flags_str = ",".join(flags) if flags else "(none)"
    mount_type = "bind" if bind else (f"fs_type={fs_type}" if fs_type else "default")
    logger.info(
        f"Mounting {src!r} -> {tgt!r} ({mount_type}) with flags: {flags_str}"
        + (f", timeout: {timeout}s" if timeout else "")
    )

    def do_mount():
        executable["-vvv", src, tgt] & logger.pipe_info("mount: ")
        if need_ro_remount:
            logger.info(f"Remounting {tgt!r} as read-only")
            cmd.mount["-o", "remount,ro", tgt] & logger.pipe_info("mount: ")

    if metrics_registry:
        metrics_manager = metrics_registry.mount(metrics_operation)
    else:
        metrics_manager = nullcontext()

    with metrics_manager, timing() as timer:
        try:
            if timeout:
                run_with_timeout(do_mount, timeout)
            else:
                do_mount()
        except (TimeoutError, ProcessTimedOut):
            raise MountFailed(
                detail=f"mount timed out after {timeout}s",
                src=src,
                tgt=tgt,
                mount_options=flags,
            )
        except ProcessExecutionError as exc:
            raise MountFailed(detail=exc.stderr, src=src, tgt=tgt, mount_options=flags)

    logger.info(f"Mount succeeded in {timer.elapsed}: {src!r} -> {tgt!r}")


def mount_tmpfs(tgt, size=META_TMPFS_SIZE, mode="0700", timeout=None):
    """Mount an empty tmpfs at tgt for storing .vast-csi-meta before the volume mount."""
    flags = f"size={size},mode={mode}"
    mount(
        src="tmpfs",
        tgt=tgt,
        fs_type="tmpfs",
        flags=flags,
        timeout=timeout,
    )


def umount_tmpfs(path, ignore_not_mounted=True, lazy=False, timeout=None):
    """Unmount the tmpfs meta overlay only (`umount -t tmpfs`). Never the volume."""
    return umount(
        path,
        ignore_not_mounted=ignore_not_mounted,
        lazy=lazy,
        timeout=timeout,
        fs_type="tmpfs",
    )


def umount(path, ignore_not_mounted=False, lazy=False, metrics_registry=None, metrics_operation="block_mount", timeout=None, fs_type=None):
    """Unmount a path with run_with_timeout when timeout is set."""
    logger.info(
        f"Unmounting {path!r}"
        + (f" (fs_type={fs_type})" if fs_type else "")
        + (f" with timeout: {timeout}s" if timeout else "")
    )

    def do_umount():
        flags = ["-v"]
        if fs_type:
            flags.extend(["-t", fs_type])
        if lazy:
            flags.append("-l")
        return cmd.umount[flags + [path]].run()

    if metrics_registry:
        metrics_manager = metrics_registry.umount(metrics_operation)
    else:
        metrics_manager = nullcontext()

    with metrics_manager, timing() as timer:
        try:
            if timeout:
                run_with_timeout(do_umount, timeout)
            else:
                do_umount()
        except TimeoutError:
            raise UmountTimedOut(f"umount timed out after {timeout}s for path: {path}")
        except ProcessExecutionError as exc:
            stderr = exc.stderr or ""
            # `umount -t tmpfs PATH` prints "no mount point specified" when no tmpfs is there.
            if "not mounted" in stderr or "no mount point specified" in stderr:
                if ignore_not_mounted:
                    logger.info(f"Umount: {path!r} is not mounted (ignored)")
                    return False
                logger.warning(f"Umount failed - {path!r} is not mounted (race?)")
                return False
            raise

    logger.info(f"Umount succeeded in {timer.elapsed}: {path!r}")
    return True


@contextmanager
def temporary_mount(src, tgt_dir, fs_type, readonly=False, timeout=None):
    """
    Temporary filesystem mount (e.g. resize, integrity probe on block devices).
    """
    mount_flags = []
    if readonly:
        mount_flags.append("ro")
    if fs_type == "xfs":
        mount_flags.insert(0, "nouuid")

    with TemporaryDirectory(dir=tgt_dir) as temp_mount_point:
        bind = fs_type != "xfs"
        if bind:
            temp_mount_point = os.path.join(temp_mount_point, "device")
            open(temp_mount_point, "a").close()
        mount(
            src=src,
            tgt=temp_mount_point,
            bind=bind,
            fs_type=fs_type if not bind else None,
            flags=mount_flags or None,
            timeout=timeout,
        )
        try:
            yield temp_mount_point
        finally:
            umount(temp_mount_point, ignore_not_mounted=True, timeout=timeout)



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


def _check_ext_integrity(device: str):
    """ext3/ext4: run fsck before mount on re-attached or cloned volumes."""
    try:
        host_commands.e2fsck.get_executable("-a", device) & logger.pipe_info("e2fsck: ")
    except ProcessExecutionError as exc:
        # fsck returns 1 if it finds and fixes issues
        if exc.retcode == 1:
            logger.warning(f"fsck found and fixed issues on {device}")
        else:
            raise


def _get_xfs_superblock_inprogress(device: str):
    """Return XFS superblock inprogress field as a string, or None if unavailable."""
    retcode, stdout, stderr = cmd.xfs_db[
        "-r", "-c", "sb 0", "-c", "p", device
    ].run(retcode=None, timeout=XFS_DB_TIMEOUT)
    if retcode != 0:
        logger.warning(
            f"Could not read XFS superblock on {device} (xfs_db exit {retcode}): {stderr}"
        )
        return None
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("inprogress"):
            return stripped.split("=", 1)[1].strip()
    return None


def _check_xfs_integrity(device: str):
    """
    Interrupted mkfs detection for XFS (superblock inprogress != 0).
    """
    inprogress = _get_xfs_superblock_inprogress(device)
    if inprogress in (None, "0"):
        return
    raise FilesystemIntegrityError(
        f"XFS on {device} has superblock inprogress={inprogress} "
        "(interrupted mkfs); refusing to continue staging"
    )


@contextmanager
def _probe_filesystem_mount(device: str, fs_type: str, timeout: int = 120):
    """
    Read-only mount probe — same class of check as NodePublishVolume mount.
    Staging bind-mounts the block device only and does not validate the filesystem.
    """
    mount_flags = ["ro"]
    if fs_type == "xfs":
        mount_flags.insert(0, "nouuid")

    with tempfile.TemporaryDirectory(prefix="vast-csi-fs-probe-") as tmpdir:
        mount_point = os.path.join(tmpdir, "mnt")
        os.makedirs(mount_point)
        mount(
            device,
            mount_point,
            fs_type=fs_type,
            flags=mount_flags,
            timeout=timeout,
        )
        try:
            yield mount_point
        finally:
            umount(mount_point, ignore_not_mounted=True, timeout=timeout)


def _probe_mount_readonly(device: str, fs_type: str, timeout: int = 120):
    logger.info(f"Probing {fs_type} mount readiness on {device}...")
    try:
        with _probe_filesystem_mount(device, fs_type, timeout=timeout):
            logger.info(f"{fs_type} mount readiness probe succeeded on {device}")
    except (MountFailed, UmountTimedOut) as exc:
        raise FilesystemIntegrityError(
            f"{fs_type} on {device} is not mountable: {exc}. "
            "Staging cannot complete until the underlying issue is resolved."
        ) from exc


def check_fs_integrity(device: str, fs_type: str, mount_timeout: int = 20, run_repair: bool = True):
    """Validate filesystem health before staging completes."""
    if run_repair:
        if fs_type in ("ext3", "ext4"):
            _check_ext_integrity(device)
        elif fs_type == "xfs":
            _check_xfs_integrity(device)
        else:
            raise FilesystemIntegrityError(
                f"Unsupported filesystem type {fs_type!r} for integrity check. "
                f"Supported: ext3, ext4, xfs"
            )
    _probe_mount_readonly(device, fs_type, timeout=mount_timeout)


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
    """Resize ext3/ext4 filesystem.

    When the device was restored from a snapshot taken of a live (mounted)
    filesystem, the superblock retains the dirty flag.  resize2fs refuses to
    proceed in that case and exits 1 with "Please run 'e2fsck -f' first."
    We catch that specific failure, run a bounded e2fsck -f to replay the
    journal and clear the flag, then retry resize2fs.
    """
    try:
        cmd.resize2fs[device] & logger.pipe_info("resize2fs: ")
    except ProcessExecutionError as exc:
        if exc.retcode == 1 and "e2fsck -f" in (exc.stderr or ""):
            logger.warning(
                f"resize2fs requires e2fsck on {device} (snapshot of live fs detected) — "
                f"running e2fsck -f with 5-minute timeout"
            )
            host_commands.e2fsck.get_executable("-f", "-y", device).run(timeout=5 * 60, retcode=None)
            cmd.resize2fs[device] & logger.pipe_info("resize2fs: ")
        else:
            raise
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


class ResourceLockedError(Exception):
    """Raised when a resource is already locked by another operation."""
    pass


class LockedResource:
    """Context manager for locking a resource."""
    def __init__(self, resource_id):
        self.resource_id = resource_id
        self.message = f"Resource {resource_id} is currently locked"

    def set_message(self, message: str):
        self.message = message

    @contextmanager
    def with_message(self, message: str):
        prev_message = self.message
        self.set_message(message)
        yield
        self.set_message(prev_message)

    def fail(self):
        raise ResourceLockedError(self.message)

    def abort(self):
        raise Abort(types.ABORTED, self.message)


@contextmanager
def resource_locked(resource_id, _locks={}, _global_lock=RLock(), abort_on_error=False, message=None):
    """
    Ensures exclusive access to a resource (volume, volume group, etc.).
    
    Prevents concurrent operations on the same resource such as:
    - Volume formatting/resizing
    - Volume group creation/modification
    - Replication operations
    - Any operation requiring exclusive access
    
    Args:
        resource_id: Unique identifier for the resource to lock
        abort_on_error: If True, raise Abort(ABORTED) on contention instead of
                        ResourceLockedError, so the gRPC framework returns a clean
                        ABORTED status without a traceback.
        message: Optional message set atomically on the LockedResource before it is
                 inserted into _locks, guaranteeing every concurrent caller that hits
                 contention always sees the verbose message.
    
    Raises:
        ResourceLockedError: If the resource is already locked (abort_on_error=False)
        Abort: If the resource is already locked (abort_on_error=True)
    """
    logger.debug(f"Attempting to acquire lock for resource {resource_id}")

    with _global_lock:
        if resource_id in _locks:
            if abort_on_error:
                _locks[resource_id].abort()
            else:
                _locks[resource_id].fail()

        locked_resource = LockedResource(resource_id)
        if message:
            locked_resource.set_message(message)
        _locks[resource_id] = locked_resource

    try:
        yield locked_resource
    finally:
        with _global_lock:
            _locks.pop(resource_id, None)
        logger.debug(f"Lock released for resource {resource_id}")
