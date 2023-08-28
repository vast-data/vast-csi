import re
from datetime import datetime
from ipaddress import summarize_address_range, ip_address
from requests.exceptions import HTTPError  # noqa

from plumbum import local
from easypy.caching import locking_cache

from easypy.tokens import (
    Token,
    ROUNDROBIN,
    RANDOM,
)
from . import csi_types as types


LOAD_BALANCING_STRATEGIES = {ROUNDROBIN, RANDOM}


PATH_ALIASES = {
    re.compile('.*/site-packages'): '*',
    re.compile("%s/" % local.cwd): ''
}


@locking_cache
def clean_path(path):
    path = str(local.path(path))  # absolutify
    for regex, alias in PATH_ALIASES.items():
        path = regex.sub(alias, path)
    return path


def get_mount(target_path):
    import psutil
    for m in psutil.disk_partitions(all=True):
        if m.mountpoint == target_path:
            return m


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


def parse_load_balancing_strategy(load_balancing: str):
    """Convert load balancing to 'Token' representation."""
    lb = Token(load_balancing.upper())
    if lb not in LOAD_BALANCING_STRATEGIES:
        raise Exception(
            f"invalid load balancing strategy: {lb} (use {'|'.join(LOAD_BALANCING_STRATEGIES)})"
        )
    return lb


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
    for opt in mount_options.split(","):
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
