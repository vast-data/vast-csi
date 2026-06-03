import os
import re
import time
import json
from contextlib import contextmanager
from plumbum import local, cmd
from plumbum.commands.processes import ProcessExecutionError, ProcessTimedOut
from easypy.bunch import Bunch, bunchify
from easypy.collections import listify
from vast_csi.exceptions import DeviceNotQuiesced
from vast_csi.filesystem_utils import hostcmd
from vast_csi.logging import logger


DEVICE_NAME_RGX = re.compile(r"nvme\d+n\d+")
BLOCK_DEVICE_INFO_PATH = local.path("/sys/block")
NVME_CLASS_PATH = local.path("/sys/class/nvme")


def try_nvme_probes():
    """
    Load and verify NVMe kernel modules and log NVMe version.
    This function attempts to load the `nvme` and `nvme-tcp` kernel modules
    using the `modprobe` utility and logs the results. It then retrieves the
    NVMe version using the `nvme` command-line tool and logs the version.
    If the nvme-tcp module is not available (e.g. on control-plane nodes with
    minimal kernels), logs an error and returns without raising.
    """
    try:
        hostcmd.modprobe.get_executable("nvme-tcp") & logger.pipe_info("nvme: ")
        nvme_version = "; ".join(hostcmd.nvme('version').splitlines())
        logger.info(f"nvme version: {nvme_version}")
    except Exception as e:
        logger.error(
            "nvme-tcp module not available: %s. Block volumes will not work on this node.",
            e,
        )


def is_native_multipath_enabled():
    try:
        with open("/sys/module/nvme_core/parameters/multipath", "r") as f:
            return f.read().strip() == "Y"
    except Exception:
        return False

def get_hostnqn_from_sysfs(subsystem):
    """
    Read HostNQN from sysfs for a given NVMe subsystem.

    This is a fallback for older nvme-cli versions (1.x) that don't report
    HostNQN in the `nvme list-subsys` output.

    Args:
        subsystem: Subsystem object with Paths containing controller names

    Returns:
        str: The HostNQN read from sysfs, or None if not found
    """
    # Pick the first controller from the subsystem's paths
    if not subsystem.Paths:
        logger.warning(f"Subsystem {subsystem.Name} has no paths")
        return None

    controller_name = subsystem.Paths[0].Name
    hostnqn_path = NVME_CLASS_PATH / controller_name / "hostnqn"

    if hostnqn_path.exists():
        return hostnqn_path.read().strip()

    logger.warning(f"hostnqn not found for controller {controller_name}")
    return None

def list_nvme_sessions():
    """
    Example output:
    {
    "HostNQN":"nqn.2014-08.com.vastcsiblock:l112lg1-v2",
    "HostID":"94300544-77e5-4544-a504-cf6778a60f5d",
    "Subsystems":[
      {
        "Name":"nvme-subsys1",
        "NQN":"nqn.2024-08.com.vastdata:default:myblock",
        "IOPolicy":"numa",
        .....
    """
    stdout = hostcmd.nvme("list-subsys", "-o", "json")
    if result := bunchify(json.loads(stdout)):
        # `nvme-cli` version 1.x returns a dictionary, while version 2.x returns a list.
        # To ensure compatibility with both versions, `listify` is used to standardize the output.
        return listify(result)
    return []


def get_connected_session(host_nqn: str, subsystem_nqn: str):
    """
    Checks if the host is connected to the subsystem.

    This function handles compatibility with both old (1.x) and new (2.x) nvme-cli versions:
    - nvme-cli 1.x: Does not return the HostNQN field in `nvme list-subsys` output
    - nvme-cli 2.x: Returns the HostNQN field

    For nvme-cli 1.x, we fall back to reading HostNQN from sysfs to properly verify
    that the connected subsystem matches the expected host NQN.

    Contract:
      - list_nvme_sessions() -> Iterable[Session]
      - Session.HostNQN: str | None   (None for nvme-cli 1.x parsing)
      - Session.HostID: str
      - Session.Subsystems: list[Subsystem]
      - Subsystem.NQN: str
      - Subsystem.Name: str

    Args:
        host_nqn: Expected host NQN that CSI wants to use
        subsystem_nqn: The subsystem NQN to check for connection

    Returns:
        Subsystem object if connected with matching host NQN, None otherwise
    """
    host_nqn = host_nqn.strip()
    subsystem_nqn = subsystem_nqn.strip()

    warned_no_hostnqn = False

    for session in list_nvme_sessions():
        # 1. Find the target subsystem first (so sysfs fallback is tied to the right subsys)
        target = None
        for subsys in session.Subsystems:
            if subsys.NQN.strip() == subsystem_nqn:
                target = subsys
                break
        if target is None:
            continue

        # 2. Resolve HostNQN
        reported_host_nqn = session.get("HostNQN", "").strip()
        if not reported_host_nqn:
            if not warned_no_hostnqn:
                logger.warning(
                    "nvme-cli output did not include HostNQN; attempting sysfs fallback for matching session(s)."
                )
                warned_no_hostnqn = True

            actual_host_nqn = get_hostnqn_from_sysfs(target)
            if actual_host_nqn is None:
                logger.error(
                    f"Cannot determine actual HostNQN for session host_id={session.get('HostID', 'unknown')}. "
                    f"Expected host_nqn={host_nqn}. Will NOT assume match."
                )
                continue

            reported_host_nqn = actual_host_nqn.strip()
            logger.info(f"Read HostNQN from sysfs: {reported_host_nqn}")

        # 3. Verify
        if reported_host_nqn == host_nqn:
            return target

        logger.debug(
            f"Subsystem NQN matched but HostNQN mismatch: expected={host_nqn}, actual={reported_host_nqn}"
        )


def list_nvme_devices():
    """
    Returns list of NVMe devices.
    Device example:
    {
      "NameSpace":2,
      "DevicePath":"/dev/nvme1n1",
      "GenericPath":"/dev/ng1n1",
      "Firmware":"24.05",
      "ModelNumber":"VastData",
      "SerialNumber":"VastData",
      "UsedBytes":0,
      "MaximumLBA":20971520,
      "PhysicalSize":10737418240,
      "SectorSize":512
    }
    """
    stdout = hostcmd.nvme("list", "-o", "json")
    if result := bunchify(json.loads(stdout)):
        return result.Devices
    return []


def get_nvme_device_by_nguid(nguid):
    nguid = nguid.replace("-", "")
    for path in BLOCK_DEVICE_INFO_PATH.iterdir():
        dev_name = path.name
        nguid_path = path["nguid"]
        if re.match(DEVICE_NAME_RGX, dev_name) and nguid_path.exists():
            if nguid_path.read().replace("-", "").strip() == nguid:
                return Bunch(
                    Name=dev_name,
                    DevicePath=f"/dev/{dev_name}",
                )


def get_nvme_device_info(device_path):
    """
    Get NVMe device information.
    Example output:
    {
      "nsze":20971520,
      "ncap":20971520,
      ................
      "endgid":0,
      "eui64":"0000000000000000",
      "nguid":"2e1de820865922178c87260002000000",
      "lbafs":[
        {
          "ms":0,
          "ds":9,
          "rp":0
        }
      ],
      "vs":[
      ]
    }
    """
    stdout = hostcmd.nvme("id-ns", device_path, "-o", "json")
    return Bunch.from_json(stdout)


def get_nvme_device_stats(device_path):
    """Get NVMe device stats by device path."""
    info = get_nvme_device_info(device_path)
    # Lower 4 bits specifically represent the current LBA format index
    flbas = info.flbas & 0xF
    lba_size = 1 << info.lbafs[flbas]["ds"]
    used_bytes = info.nuse * lba_size
    total_bytes = info.nsze * lba_size
    return Bunch(
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        available_bytes=total_bytes - used_bytes,
    )


def get_controller_info(device_path):
    """
    Get NVMe controller information.
    Example output:
    {
      "vid":0,
      "ssvid":0,
      "sn":"00000000",
      "mn":"INTEL SSDPE2K
      "subnqn":"nqn.2024-08.com.vastdata:default:myblock",
        ................
    """
    stdout = hostcmd.nvme("id-ctrl", device_path, "-o", "json")
    return Bunch.from_json(stdout)


def connect_nvme_targets(discovery_server, host_nqn, host_id, subsystem_nqn):
    """
    Connects to all NVMe targets associated with a given Discovery Controller and subsystem.

    Args:
        discovery_server (str): The IP address or hostname of the Discovery Controller.
        host_nqn (str): The Host NQN (NVMe Qualified Name) used to identify the host.
        host_id (str): User defined Host ID.
        subsystem_nqn (str): The subsystem NQN to verify connection.

    Returns:
        Subsystem object if connected successfully, None otherwise.
    """
    args = [
        "connect-all",
        "-t", "tcp",
        "-a", discovery_server,
        "-q", host_nqn,
        "-I", host_id,
    ]
    hostcmd.nvme.get_executable(*args) & logger.pipe_info("nvme")

    # Return the connected session
    return get_connected_session(host_nqn=host_nqn, subsystem_nqn=subsystem_nqn)


def change_io_policy(device_name, io_policy):
    """
    Changes the I/O policy of a given NVMe device.
    Args:
        device_name (str): The name of the NVMe device (e.g., '/dev/nvme0n1').
        io_policy (str): The I/O policy to set for the device (e.g., 'numa').
    """
    with BLOCK_DEVICE_INFO_PATH[device_name]["device/iopolicy"].open("w") as f:
        f.write(io_policy)


def disable_nvme_timeout(subsystem):
    """
    Disables the NVMe controller loss timeout by setting ctrl_loss_tmo to -1 for all
    controllers in the subsystem.

    Args:
        subsystem: Subsystem object with Paths containing controller names
    """
    if not subsystem.Paths:
        logger.warning(f"Subsystem {subsystem.Name} has no paths")
        return

    # Disable timeout for all controllers in the subsystem
    for path in subsystem.Paths:
        ctrl_name = path.Name
        ctrl_loss_tmo_path = NVME_CLASS_PATH / ctrl_name / "ctrl_loss_tmo"

        if ctrl_loss_tmo_path.exists():
            with ctrl_loss_tmo_path.open("w") as f:
                f.write("-1")
            logger.info(f"Disabled timeout for NVMe controller {ctrl_name!r}")
        else:
            logger.warning(f"ctrl_loss_tmo not found for controller {ctrl_name!r}")


def set_block_device_readonly(device_path):
    """Set a block device read-only at the kernel level using blockdev --setro."""
    cmd.blockdev["--setro", device_path].run()


def set_block_device_readwrite(device_path):
    """Clear the kernel-level read-only flag on a block device using blockdev --setrw."""
    cmd.blockdev["--setrw", device_path].run()


@contextmanager
def device_rw(device_path, mount_path=None, enabled=True):
    """Transiently lift read-only protection on a block device for resize operations.

    When enabled=False this is a no-op (avoids caller-side conditionals).
    """
    if not enabled:
        yield
        return

    set_block_device_readwrite(device_path)
    if mount_path:
        logger.info(f"Temporarily remounting {mount_path} as rw to clear SB_RDONLY for resize")
        cmd.mount["-o", "remount,rw", mount_path].run()
    try:
        yield
    finally:
        if mount_path:
            cmd.mount["-o", "remount,ro", mount_path].run()
            logger.info(f"Remounted {mount_path} back to read-only after resize")
        set_block_device_readonly(device_path)


def _read_inflight(device_name):
    """Read /sys/block/<dev>/inflight as (reads, writes). Returns (-1, -1) if unavailable."""
    inflight_path = BLOCK_DEVICE_INFO_PATH / device_name / "inflight"
    if not inflight_path.exists():
        return (-1, -1)
    try:
        parts = inflight_path.read().split()
        if len(parts) >= 2:
            return (int(parts[0]), int(parts[1]))
    except (ValueError, OSError) as exc:
        logger.warning(f"Failed to read {inflight_path}: {exc}")
    return (-1, -1)


def _log_device_diagnostics(device_name):
    """Emit a compact diagnostic snapshot of the device's sysfs state.

    Called on the failure path of verify_device_quiesced so the CSI log has
    enough context to triage why the check refused without needing to grab
    a fresh bundle. Best-effort: never raises.
    """
    sys_block = BLOCK_DEVICE_INFO_PATH / device_name
    try:
        holders_dir = sys_block / "holders"
        holders = (
            [p.name for p in holders_dir.list()] if holders_dir.exists() else []
        )
        reads, writes = _read_inflight(device_name)
        logger.warning(
            "verify_device_quiesced diagnostics for %s: "
            "holders=%s inflight=(reads=%s, writes=%s)",
            device_name, holders, reads, writes,
        )
    except Exception as exc:
        logger.warning(f"verify_device_quiesced diagnostics for {device_name} failed: {exc}")


def verify_device_quiesced(device_path, timeout_s=5):
    """
    Verify an NVMe block device is safely idle before letting an
    unstage/unmap handoff proceed.

    Checks (cheap, run in order):
      1. /sys/block/<dev>/holders is empty (no upper layer still using it).
      2. `blockdev --flushbufs <device>` completes (no hung I/O path).
      3. /sys/block/<dev>/inflight reads "0 0" within `timeout_s` seconds.

    For LUKS-encrypted volumes the caller passes "/dev/mapper/luks-<uuid>",
    which is a symlink to "/dev/dm-N". We resolve it and run the checks on
    the dm-crypt node: dm-crypt exposes its own holders/inflight counters and
    its blockdev --flushbufs propagates through to the backing NVMe, so the
    same logic catches a stuck path whether or not encryption is enabled.

    Args:
        device_path (str): block device path, e.g. "/dev/nvme3n40" or
            "/dev/mapper/luks-<uuid>".
        timeout_s (int): how long to poll inflight before giving up; also the
            timeout for blockdev --flushbufs.

    Raises:
        DeviceNotQuiesced: if any check fails. Caller should translate to
            a CSI FAILED_PRECONDITION error so kubelet retries.
    """
    # Resolve symlinks so /dev/mapper/luks-<uuid> -> /dev/dm-N. The kernel
    # exposes sysfs counters under /sys/block/<resolved-basename>, never
    # under the symlink name.
    resolved_path = os.path.realpath(device_path)
    device_name = os.path.basename(resolved_path)

    sys_block = BLOCK_DEVICE_INFO_PATH / device_name
    if not sys_block.exists():
        # Not a top-level block device sysfs node (e.g., a partition like
        # nvme0n1p1 lives under /sys/block/nvme0n1/, or device already gone).
        # Don't gate unstage on a check we can't run.
        logger.warning(
            f"verify_device_quiesced: skipping, no sysfs entry for {device_name!r} "
            f"(resolved from {device_path!r})"
        )
        return

    # 1. Holders must be empty (no FS, no dm-crypt, no LVM still attached).
    #    For LUKS volumes we're checking the dm-N device, whose holders are
    #    empty once the filesystem is unmounted (which we haven't done yet --
    #    but FS mounts aren't block-layer holders, only stacked block devices
    #    like dm/md/lvm are listed here).
    holders_dir = sys_block / "holders"
    if holders_dir.exists():
        holders = [p.name for p in holders_dir.list()]
        if holders:
            _log_device_diagnostics(device_name)
            raise DeviceNotQuiesced(
                f"device {device_name} still has holders: {holders}"
            )

    # 2. Force a flush. On a hung path this blocks or fails; on a healthy
    #    path it is effectively a no-op (umount already flushed). For LUKS
    #    this flushes the dm-crypt queue, which in turn flushes the backing
    #    NVMe -- so a stuck array path is still caught here.
    try:
        cmd.blockdev["--flushbufs", resolved_path].run(timeout=timeout_s)
    except (ProcessTimedOut, ProcessExecutionError) as exc:
        _log_device_diagnostics(device_name)
        raise DeviceNotQuiesced(
            f"blockdev --flushbufs failed for {device_name}: {exc}"
        )

    # 3. Inflight must drain to 0/0. If sysfs doesn't expose the counters
    #    (_read_inflight returns (-1, -1)), don't gate unstage on a check we
    #    can't actually run -- holders + flushbufs above already cover the
    #    main failure modes.
    reads, writes = _read_inflight(device_name)
    if reads == -1:
        logger.warning(
            f"verify_device_quiesced: inflight counters unavailable for "
            f"{device_name}, skipping drain check"
        )
    else:
        deadline = time.monotonic() + timeout_s
        while (reads != 0 or writes != 0) and time.monotonic() < deadline:
            time.sleep(0.2)
            reads, writes = _read_inflight(device_name)

        if reads != 0 or writes != 0:
            _log_device_diagnostics(device_name)
            raise DeviceNotQuiesced(
                f"device {device_name} has inflight I/O reads={reads} writes={writes} "
                f"after {timeout_s}s"
            )

    logger.info(f"verify_device_quiesced: {device_name} is idle")
