import os
import re
import uuid
import psutil
import threading
from pprint import pformat
from datetime import datetime
from ipaddress import summarize_address_range, ip_address
from base64 import b32encode
from random import getrandbits
from requests.exceptions import HTTPError  # noqa

from plumbum import local
from easypy.caching import locking_cache
from easypy.collections import listify
from . import csi_types as types


PATH_ALIASES = {
    re.compile('.*/site-packages'): '*',
    re.compile("%s/" % local.cwd): ''
}


def stringify_dict(d):
    """Convert dictionary to string representation for line-by-line logging."""
    yield from pformat(d).splitlines()


@locking_cache
def clean_path(path):
    path = str(local.path(path))  # absolutify
    for regex, alias in PATH_ALIASES.items():
        path = regex.sub(alias, path)
    return path


def run_with_timeout(func, timeout, *args, **kwargs):
    """
    Run a function with a timeout using a daemon thread.
    
    Args:
        func: Function to execute
        timeout: Timeout in seconds
        *args: Positional arguments to pass to func
        **kwargs: Keyword arguments to pass to func
    
    Returns:
        The return value of func
    
    Raises:
        TimeoutError: If func takes longer than timeout
        Exception: Any exception raised by func
    """
    result = {'value': None, 'error': None, 'completed': False}
    
    def worker():
        try:
            result['value'] = func(*args, **kwargs)
            result['completed'] = True
        except Exception as e:
            result['error'] = e
            result['completed'] = True
    
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    
    if not result['completed']:
        raise TimeoutError(f"Operation timed out after {timeout}s")
    
    if result['error']:
        raise result['error']
    
    return result['value']


def get_mount(target_path, timeout=5):
    """
    Get mount information for the target path.
    
    Args:
        target_path: Path to check for mount
        timeout: Timeout in seconds (default: 5). If psutil.disk_partitions()
                 takes longer than this (e.g., due to unreachable NFS mount),
                 a TimeoutError will be raised.
    """

    def check_mount():
        partitions = psutil.disk_partitions(all=True)
        for m in partitions:
            if m.mountpoint == target_path:
                return m
        return None
    
    try:
        return run_with_timeout(check_mount, timeout)
    except TimeoutError:
        error_msg = (
            f"get_mount() timed out after {timeout}s while checking {target_path}. "
            f"This usually indicates an unreachable NFS mount. "
            f"Check network connectivity to NFS server."
        )
        raise TimeoutError(error_msg)


def path_exists(path, timeout=5):
    """
    Check if a path exists with a timeout.
    
    Args:
        path: Path to check (can be string or plumbum path object)
        timeout: Timeout in seconds (default: 5). If the exists check
                 takes longer than this (e.g., due to unreachable NFS mount),
                 a TimeoutError will be raised.
    """

    def check_exists():
        # Convert plumbum path to string if needed
        path_str = str(path)
        return os.path.exists(path_str)
    
    try:
        return run_with_timeout(check_exists, timeout)
    except TimeoutError:
        error_msg = (
            f"path_exists() timed out after {timeout}s while checking {path}. "
            f"This usually indicates an unreachable NFS mount. "
            f"Check network connectivity to NFS server."
        )
        raise TimeoutError(error_msg)


def nice_format_traceback(self):

    _RECURSIVE_CUTOFF = 3

    if True:  # indent like the original code in the traceback module
        result = []
        last_file = None
        last_line = None
        last_name = None
        count = 0

        lines = []

        for frame in self:
            if (last_file is None or last_file != frame.filename or
                last_line is None or last_line != frame.lineno or
                last_name is None or last_name != frame.name):
                if count > _RECURSIVE_CUTOFF:
                    count -= _RECURSIVE_CUTOFF
                    result.append(
                        f'  [Previous line repeated {count} more '
                        f'time{"s" if count > 1 else ""}]\n'
                    )
                last_file = frame.filename
                last_line = frame.lineno
                last_name = frame.name
                count = 0
            count += 1
            if count > _RECURSIVE_CUTOFF:
                continue

            filename, lineno, name, line = frame.filename, frame.lineno, frame.name, frame.line

            filename = clean_path(filename)
            left = f"  {filename}:{lineno} "
            right = f" {name}"

            blame = None  # can't 'blame' inside the infra container

            lines.append((len(left) + len(right), len(line), left, right, line, blame))
            if frame.locals:
                for name, value in sorted(frame.locals.items()):
                    line = f"{name} = {value}"
                    lines.append((len(left) + len(right), 0, '', '', line, ''))

        lwidth = max((args[0] for args in lines), default=0) + 4
        rwidth = max((args[1] for args in lines), default=0) + 2

        for _, _, left, right, line, blame in lines:
            item = left.ljust(lwidth - len(right), ".") + right
            if line:
                item = f'{item} >> {line.strip():{rwidth}}'
                if blame:
                    item += blame
            result.append(item + '\n')

        if count > _RECURSIVE_CUTOFF:
            count -= _RECURSIVE_CUTOFF
            result.append(
                f'  [Previous line repeated {count} more '
                f'time{"s" if count > 1 else ""}]\n'
            )
        return result


def patch_traceback_format():
    from traceback import StackSummary
    orig_format_traceback, StackSummary.format = StackSummary.format, nice_format_traceback


def normalize_mount_options(mount_options: str):
    """Convert mount options to list if mount options were provided as string on StorageClass parameters level."""
    s = mount_options.strip()
    mount_options = list({p for p in s.split(",") if p})
    return mount_options


def string_to_proto_timestamp(str_ts: str):
    """Convert string to protobuf.Timestamp"""
    t = datetime.fromisoformat(str_ts.rstrip("Z")).timestamp()
    return types.Timestamp(seconds=int(t), nanos=int(t % 1 * 1e9))


def is_ver_nfs4_present(mount_options: str) -> bool:
    """Check if vers=4 or nfsvers=4 mount option is present in `mount_options` string"""
    for opt in listify(mount_options):
        name, sep, value = opt.partition("=")
        if name in ("vers", "nfsvers") and value.startswith("4"):
            return True
    return False


def generate_ip_range(ip_ranges):
    """
    Generate list of ips from provided ip ranges.
    `ip_ranges` should be list of ranges where fist ip in range represents start ip and second is end ip
    eg: [["15.0.0.1", "15.0.0.4"], ["10.0.0.27", "10.0.0.30"]]
    """
    return [
        ip.compressed
        for start_ip, end_ip in ip_ranges for net in summarize_address_range(ip_address(start_ip), ip_address(end_ip))
        for ip in net
    ]


def get_random_fqdn_prefix():
    return b32encode(getrandbits(16).to_bytes(2, "big")).decode("ascii").rstrip("=")


def is_valid_ip(ip_str):
    try:
        ip_address(ip_str)
        return True
    except ValueError:
        return False


def wrap_ipv6(ip_or_host: str) -> str:
    try:
        ip = ip_address(ip_or_host)
        if ip.version == 6:
            return f"[{ip_or_host}]"
    except ValueError:
        # Not an IP address, possibly an FQDN
        pass
    return ip_or_host


def string_to_static_uuid(value: str) -> str:
    """
    Generate a deterministic UUIDv5 based on the input string,
    using the standard DNS namespace.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, value))
