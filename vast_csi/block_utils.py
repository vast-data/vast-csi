import re
import json
from contextlib import contextmanager
from plumbum import local, cmd
from easypy.bunch import Bunch, bunchify
from easypy.collections import listify
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


def enable_passthru_err_log(device_name, subsystem):
    """
    Enable NVMe passthrough error logging for a specific device and its subsystem controllers.

    Args:
        device_name (str): NVMe namespace name (e.g. 'nvme0n1').
        subsystem: Subsystem object with Paths containing controller names.
    """
    def _write_flag(path):
        flag = path / "passthru_err_log_enabled"
        if flag.exists():
            try:
                with flag.open("w") as f:
                    f.write("1")
            except Exception as e:
                logger.warning(f"Failed to enable passthru_err_log for {path.name}: {e}")

    _write_flag(BLOCK_DEVICE_INFO_PATH / device_name)

    if not subsystem.Paths:
        logger.warning(f"Subsystem {subsystem.Name} has no paths, skipping passthru_err_log for controllers")
        return
    for path in subsystem.Paths:
        _write_flag(NVME_CLASS_PATH / path.Name)


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
