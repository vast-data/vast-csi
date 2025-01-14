import re
import json
from plumbum import local
from easypy.bunch import Bunch, bunchify
from vast_csi.filesystem_utils import hostcmd
from vast_csi.logging import logger


DEVICE_NAME_RGX = re.compile(r"nvme\d+n\d+")
BLOCK_DEVICE_INFO_PATH = local.path("/sys/block")


def try_nvme_probes():
    """
    Load and verify NVMe kernel modules and log NVMe version.
    This function attempts to load the `nvme` and `nvme-tcp` kernel modules
    using the `modprobe` utility and logs the results. It then retrieves the
    NVMe version using the `nvme` command-line tool and logs the version.
    """
    hostcmd.modprobe.get_executable("nvme-tcp") & logger.pipe_info("nvme: ")
    nvme_version = "; ".join(hostcmd.nvme('version').splitlines())
    logger.info(f"nvme version: {nvme_version}")


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
        return result
    return []


def get_connected_session(host_nqn, sybsystem_nqn):
    """Checks if the host is connected to the subsystem."""
    for session in list_nvme_sessions():
        if session.HostNQN == host_nqn:
            for subsys in session.Subsystems:
                if subsys.NQN == sybsystem_nqn:
                    return subsys


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


def get_nvme_device_by_uuid(uuid):
    """Get NVMe device UUID."""
    uuid = uuid.replace("-", "")
    for path in BLOCK_DEVICE_INFO_PATH.iterdir():
        dev_name = path.name
        nguid_path = path["nguid"]
        if re.match(DEVICE_NAME_RGX, dev_name) and nguid_path.exists():
            if nguid_path.read().replace("-", "") == uuid:
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
    lba_size = 2 ** info.lbafs[flbas]["ds"]
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


def connect_nvme_targets(discovery_server, host_nqn):
    """
     Connects to all NVMe targets associated with a given Discovery Controller and subsystem.
     Args:
         discovery_server (str): The IP address or hostname of the Discovery Controller.
         host_nqn (str): The Host NQN (NVMe Qualified Name) used to identify the host.
     """
    args = [
        "connect-all",
        "-t", "tcp",
        "-a", discovery_server,
        "-q", host_nqn,
        "--dump-config",
        "--verbose",
    ]
    hostcmd.nvme.get_executable(*args) & logger.pipe_info("nvme")


def change_io_policy(device_name, io_policy):
    """
    Changes the I/O policy of a given NVMe device.
    Args:
        device_name (str): The name of the NVMe device (e.g., '/dev/nvme0n1').
        io_policy (str): The I/O policy to set for the device (e.g., 'numa').
    """
    with BLOCK_DEVICE_INFO_PATH[device_name]["device/iopolicy"].open("w") as f:
        f.write(io_policy)
