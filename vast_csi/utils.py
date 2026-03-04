import os
import re
import uuid
import psutil
import threading
from contextlib import contextmanager
from pprint import pformat
from datetime import datetime, timedelta
from ipaddress import summarize_address_range, ip_address
from base64 import b32encode
from random import getrandbits
from requests.exceptions import HTTPError  # noqa

from plumbum import local
from easypy.caching import locking_cache
from easypy.collections import listify
from . import csi_types as types
from .exceptions import Abort


@contextmanager
def to_abort(code=types.ABORTED):
    """
    Context manager that converts any exception into Abort(ABORTED, ...).

    Useful for wrapping VMS API calls in gRPC handlers where internal errors
    (e.g., HTTP 503 from VMS) should be surfaced as gRPC ABORTED status
    """
    try:
        yield
    except Abort:
        raise
    except Exception as exc:
        raise Abort(code, str(exc)) from exc


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


def parse_string_parameters(params: dict) -> dict:
    """
    Parse string parameters (from StorageClass, SnapshotClass, BucketClass, etc.)
    into properly typed values.
    
    Kubernetes resource parameters are always string-to-string dictionaries.
    This function converts them to appropriate Python types:
    - "true"/"false" (case-insensitive) → bool
    - String numbers → int or float
    - Everything else → kept as string
    
    Args:
        params: Dictionary with string keys and string values from K8s resource parameters
        
    Returns:
        Dictionary with the same keys but properly typed values
        
    Example:
        >>> parse_string_parameters({
        ...     "create_dir": "true",
        ...     "capacity": "1000",
        ...     "ratio": "1.5",
        ...     "name": "my-volume"
        ... })
        {
            "create_dir": True,
            "capacity": 1000,
            "ratio": 1.5,
            "name": "my-volume"
        }
    """
    result = {}
    
    for key, value in params.items():
        if not isinstance(value, str):
            # If it's already not a string, keep it as is
            result[key] = value
            continue
            
        # Try boolean conversion first
        value_lower = value.lower().strip()
        if value_lower in ("true", "yes", "on", "1"):
            result[key] = True
            continue
        elif value_lower in ("false", "no", "off", "0"):
            result[key] = False
            continue
        
        # Try numeric conversion
        try:
            # Try integer first (this also handles "1.0" properly)
            if '.' not in value and 'e' not in value_lower:
                result[key] = int(value)
                continue
        except (ValueError, TypeError):
            pass
        
        try:
            # Try float
            result[key] = float(value)
            continue
        except (ValueError, TypeError):
            pass
        
        # Keep as string if no conversion worked
        result[key] = value
    
    return result


def yesno_to_bool(value):
    """
    Convert a yes/no, true/false, on/off string to boolean.
    
    Args:
        value: String or boolean value
        
    Returns:
        Boolean value
        
    Raises:
        ValueError: If the string cannot be converted to boolean
    """
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        value_lower = value.lower().strip()
        if value_lower in ("true", "yes", "on", "1"):
            return True
        elif value_lower in ("false", "no", "off", "0"):
            return False
    
    raise ValueError(f"Cannot convert {value!r} to boolean")


def slugify(text: str, separator: str = "-") -> str:
    """
    Convert a string (such as IP address, hostname, or URL) into a valid slug.
    
    This function is useful for creating valid resource names from endpoints,
    IP addresses, or other identifiers that may contain special characters.
    
    Args:
        text: The input string to slugify (e.g., "192.168.1.1", "fe80::1", "host.example.com")
        separator: Character to use as separator (default: "-")
        
    Returns:
        A slugified string with only alphanumeric characters and separators
        
    Example:
        >>> slugify("192.168.1.1")
        '192-168-1-1'
        >>> slugify("fe80::1")
        'fe80-1'
        >>> slugify("host.example.com")
        'host-example-com'
        >>> slugify("10.0.0.1", separator="_")
        '10_0_0_1'
    """
    # Convert to lowercase and strip whitespace
    slug = text.lower().strip()
    
    # Replace common separators and special characters with the separator
    # This handles: dots, colons, slashes, underscores, spaces
    slug = re.sub(r'[.:/_\s]+', separator, slug)
    
    # Remove any characters that are not alphanumeric or the separator
    slug = re.sub(r'[^a-z0-9' + re.escape(separator) + r']+', '', slug)
    
    # Remove leading/trailing separators and collapse multiple separators
    slug = re.sub(r'' + re.escape(separator) + r'+', separator, slug)
    slug = slug.strip(separator)
    
    return slug


def parse_duration_to_timestamp(duration_str: str, from_time: datetime = None) -> str:
    """
    Parse a duration string (like "2H", "10m", "1d") and convert it to a timestamp.
    
    This function takes VAST duration strings from protection policies and converts
    them to absolute timestamps in the format required by the API: YYYY-mm-ddTHH:MM:SS
    
    Implementation matches VAST's internal replicate_now() method which uses
    datetime.isoformat(timespec="seconds") for timestamp formatting.
    
    Args:
        duration_str: Duration string (e.g., "2H", "30m", "1d", "1W")
                     Supported units: m (minutes), H (hours), d (days), W (weeks)
        from_time: Base datetime to add duration to (default: current time)
        
    Returns:
        Timestamp string in format "YYYY-mm-ddTHH:MM:SS"
        
    Example:
        >>> parse_duration_to_timestamp("2H")  # 2 hours from now
        '2025-11-22T18:30:00'
        >>> parse_duration_to_timestamp("30m")  # 30 minutes from now
        '2025-11-22T16:45:00'
    """
    if from_time is None:
        from_time = datetime.now()
    
    if not duration_str:
        # Default to 1 hour if no duration specified
        duration_str = "1H"
    
    # Parse the duration string using regex
    # Format: <number><unit> where unit is m, H, d, W
    match = re.match(r'^(\d+)([mHdW])$', duration_str.strip())
    
    if not match:
        raise ValueError(f"Invalid duration format: {duration_str}. Expected format: <number><unit> (e.g., '2H', '30m')")
    
    amount = int(match.group(1))
    unit = match.group(2)
    
    # Convert to timedelta
    if unit == 'm':  # minutes
        delta = timedelta(minutes=amount)
    elif unit == 'H':  # hours
        delta = timedelta(hours=amount)
    elif unit == 'd':  # days
        delta = timedelta(days=amount)
    elif unit == 'W':  # weeks
        delta = timedelta(weeks=amount)
    else:
        raise ValueError(f"Unsupported duration unit: {unit}")
    
    # Calculate expiration time
    expiration_time = from_time + delta
    
    # Format as required by VAST API using isoformat (same as VAST's internal implementation)
    # This produces format: YYYY-mm-ddTHH:MM:SS
    return expiration_time.isoformat(timespec="seconds")


def replace_path_prefix(base_path, replacement_path):
    """
    Replace the first N segments of base_path with replacement_path.
    
    This is useful for replication scenarios where you want to replicate a directory
    structure to a different base location while preserving the relative hierarchy.
    
    Args:
        base_path: Source path whose prefix will be replaced (e.g., "/foo/bar/biz")
        replacement_path: New prefix to use (e.g., "/zoo/rar")
    
    Returns:
        Path with replaced prefix (e.g., "/zoo/rar/biz")
    
    Examples:
        >>> replace_path_prefix("/foo/bar/biz", "/zoo/rar")
        '/zoo/rar/biz'
        
        >>> replace_path_prefix("/k8s", "/replication/volumes")
        '/replication/volumes'
        
        >>> replace_path_prefix("/production/team-a/app1/data", "/backup/dr-site")
        '/backup/dr-site/app1/data'
        
        >>> replace_path_prefix("/k8s/volumes", None)
        '/k8s/volumes'
    """
    if not replacement_path:
        return base_path
    
    # Normalize paths by removing trailing slashes
    base_path = base_path.rstrip('/')
    replacement_path = replacement_path.rstrip('/')
    
    # Split paths into segments (filter out empty strings from leading/trailing slashes)
    base_segments = [s for s in base_path.split('/') if s]
    replacement_segments = [s for s in replacement_path.split('/') if s]
    n_replace = len(replacement_segments)
    
    if n_replace >= len(base_segments):
        # Replacement path is longer or equal - use it directly
        return replacement_path
    else:
        # Keep remaining segments from base_path
        remaining_segments = base_segments[n_replace:]
        return replacement_path + '/' + '/'.join(remaining_segments)
