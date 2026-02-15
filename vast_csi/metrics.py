# Copyright 2026 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Metrics module for CSI operations.

This module provides comprehensive Prometheus metrics for the CSI driver:

1. CSI RPC Operation Metrics (via context manager):
   - csi_plugin_operations_total - Counter for all CSI RPC calls
   - csi_plugin_operations_seconds - Histogram for CSI RPC latency
   - Automatically records all CSI methods (NodeStageVolume, CreateVolume, etc.)

2. Node-Level Mount/Unmount Metrics (for detailed tracking):
   - csi_node_mount_operations_total - Counter for mount operations
   - csi_node_mount_duration_seconds - Histogram for mount latency
   - csi_node_umount_operations_total - Counter for unmount operations
   - csi_node_umount_duration_seconds - Histogram for unmount latency
   - csi_node_nvme_connect_operations_total - Counter for NVMe-oF connects
   - csi_node_nvme_connect_duration_seconds - Histogram for NVMe-oF latency

3. NFS Transport (xprt) Statistics:
   - Detailed NFS connection metrics from /proc/self/mountstats

Components:
- MetricsRegistry: Context manager for CSI operations, mount/unmount, and NVMe operations
- get_metrics_registry(): Factory function for creating MetricsRegistry instances
- HTTP server: Serves metrics at /metrics and health check at /health

Usage:
    # CSI operation metrics (automatic in base.py when metrics_enabled=True)
    if CONF.metrics_enabled:
        metrics_registry = get_metrics_registry(
            params, hostname=CONF.node_id, driver_name=CONF.plugin_name
        )
        with metrics_registry.csi_operation(method_name):
            # CSI method implementation
            pass
    
    # Mount/unmount metrics (explicit tracking in CSI methods)
    with metrics_registry.mount('nfs'):
        cmd.mount[src, tgt].run()

Endpoints:
- /metrics - Prometheus metrics (CSI RPCs + mount/unmount + NFS transport stats)
- /health  - Health check endpoint
"""

import json
import re
import time
import queue
import threading
from collections import Counter as CollCounter

from enum import Enum
from contextlib import contextmanager
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from plumbum.commands.processes import ProcessTimedOut
from plumbum import ProcessExecutionError
from easypy.caching import cached_property

from vast_csi.logging import logger
from vast_csi.exceptions import Abort
from vast_csi.csi_types import (
    INVALID_ARGUMENT,
    NOT_FOUND,
    ALREADY_EXISTS,
    RESOURCE_EXHAUSTED,
    FAILED_PRECONDITION,
    ABORTED,
    UNAVAILABLE,
    INTERNAL,
    UNKNOWN,
)
from vast_csi.filesystem_utils import MountInfo, hostcmd

# ================================================================
# Constants
# ================================================================

XPRT_WORKERS = 3

# Default histogram buckets for CSI operations
# Buckets: 0-1s, 1-5s, 5-20s, 20s+
DEFAULT_CSI_BUCKETS = (
    1.0,
    5.0,
    20.0,
    float("inf"),
)

# Default histogram buckets for mount/unmount/NVMe operations
# Buckets: 0-1s, 1-5s, 5-20s, 20s+
DEFAULT_MOUNT_BUCKETS = (
    1.0,
    5.0,
    20.0,
    float("inf"),
)


# ================================================================
# Operation Status Enum
# ================================================================


# Operation status enum
class OperationStatus(str, Enum):
    """Enum for operation status labels in metrics."""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


# gRPC status code mapping
def get_grpc_status_code(exception=None):
    """Map exception to gRPC status code string."""

    if exception is None:
        return "OK"

    if isinstance(exception, Abort):
        code_map = {
            INVALID_ARGUMENT: "InvalidArgument",
            NOT_FOUND: "NotFound",
            ALREADY_EXISTS: "AlreadyExists",
            RESOURCE_EXHAUSTED: "ResourceExhausted",
            FAILED_PRECONDITION: "FailedPrecondition",
            ABORTED: "Aborted",
            UNAVAILABLE: "Unavailable",
            INTERNAL: "Internal",
            UNKNOWN: "Unknown",
        }
        return code_map.get(exception.code, "Unknown")

    # Non-CSI exceptions
    return "Exception"


# ================================================================
# Metric Registration (conditional based on service type)
# ================================================================


class MetricFactory:
    """Factory for creating and caching Prometheus metrics based on service type."""

    def __init__(self, is_node_service):
        """
        Initialize the metric factory with service type.

        Args:
            is_node_service (bool): True for node service, False for controller
        """
        self.is_node_service = is_node_service

    @cached_property
    def csi_operations_total(self):
        """Get or create CSI operations total counter (available for all services)."""
        return Counter(
            "csi_plugin_operations_total",
            "Total number of CSI operations by method and status",
            ["driver_name", "method_name", "grpc_status_code", "hostname", "volume_id"],
        )

    @cached_property
    def csi_operations_seconds(self):
        """Get or create CSI operations duration histogram (available for all services)."""
        return Histogram(
            "csi_plugin_operations_seconds",
            "Duration of CSI operations in seconds",
            ["driver_name", "method_name", "grpc_status_code", "hostname", "volume_id"],
            buckets=DEFAULT_CSI_BUCKETS,
        )

    @cached_property
    def mount_operations_total(self):
        """Get or create mount operations counter (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("Mount metrics are only available for node services")
        return Counter(
            "csi_node_mount_operations_total",
            "Total number of mount operations",
            ["operation_type", "status", "hostname"],
        )

    @cached_property
    def mount_duration_seconds(self):
        """Get or create mount duration histogram (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("Mount metrics are only available for node services")
        return Histogram(
            "csi_node_mount_duration_seconds",
            "Duration of mount operations in seconds",
            ["operation_type", "hostname"],
            buckets=DEFAULT_MOUNT_BUCKETS,
        )

    @cached_property
    def umount_operations_total(self):
        """Get or create umount operations counter (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("Umount metrics are only available for node services")
        return Counter(
            "csi_node_umount_operations_total",
            "Total number of unmount operations",
            ["operation_type", "status", "hostname"],
        )

    @cached_property
    def umount_duration_seconds(self):
        """Get or create umount duration histogram (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("Umount metrics are only available for node services")
        return Histogram(
            "csi_node_umount_duration_seconds",
            "Duration of unmount operations in seconds",
            ["operation_type", "hostname"],
            buckets=DEFAULT_MOUNT_BUCKETS,
        )

    @cached_property
    def nvme_connect_operations_total(self):
        """Get or create NVMe connect operations counter (node service only)."""
        if not self.is_node_service:
            raise RuntimeError(
                "NVMe connect metrics are only available for node services"
            )
        return Counter(
            "csi_node_nvme_connect_operations_total",
            "Total number of NVMe-oF connect operations",
            ["status", "hostname"],
        )

    @cached_property
    def nvme_connect_duration_seconds(self):
        """Get or create NVMe connect duration histogram (node service only)."""
        if not self.is_node_service:
            raise RuntimeError(
                "NVMe connect metrics are only available for node services"
            )
        return Histogram(
            "csi_node_nvme_connect_duration_seconds",
            "Duration of NVMe-oF connect operations in seconds",
            ["hostname"],
            buckets=DEFAULT_MOUNT_BUCKETS,
        )

    @cached_property
    def xprt_total(self):
        """Get or create xprt total gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge("csi_node_nfs_xprt_total", "Total number of NFS transports")

    @cached_property
    def xprt_connected(self):
        """Get or create xprt connected gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_connected", "Number of NFS transports in CONNECTED state"
        )

    @cached_property
    def xprt_pending_total(self):
        """Get or create xprt pending total gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_pending_requests_total",
            "Total pending RPC requests across all transports",
        )

    @cached_property
    def xprt_backlog_total(self):
        """Get or create xprt backlog total gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_backlog_total",
            "Total backlog queue depth across all transports",
        )

    @cached_property
    def xprt_unhealthy(self):
        """Get or create xprt unhealthy gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_unhealthy", "Number of transports with potential issues"
        )

    @cached_property
    def xprt_connected_per_dest(self):
        """Get or create xprt connected state gauge per destination (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_connected_state",
            "Transport is connected (CONNECTED and BOUND flags set)",
            ["destination"],
        )

    @cached_property
    def xprt_congested(self):
        """Get or create xprt congested gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_congested_state",
            "Transport is congested (CONGESTED or CWND_WAIT flags set)",
            ["destination"],
        )

    @cached_property
    def xprt_locked(self):
        """Get or create xprt locked gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_locked_state",
            "Transport is locked (LOCKED flag set)",
            ["destination"],
        )

    @cached_property
    def xprt_pending_requests(self):
        """Get or create xprt pending requests gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_pending_requests",
            "Number of pending RPC requests for this transport",
            ["destination"],
        )

    @cached_property
    def xprt_backlog_depth(self):
        """Get or create xprt backlog depth gauge (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_backlog_depth",
            "Backlog queue depth for this transport",
            ["destination"],
        )

    @cached_property
    def xprt_mounts(self):
        """Get or create xprt mount count gauge per destination (node service only)."""
        if not self.is_node_service:
            raise RuntimeError("xprt metrics are only available for node services")
        return Gauge(
            "csi_node_nfs_xprt_mounts",
            "Number of NFS mounts using this transport",
            ["destination"],
        )


# Global metric factory instance (initialized during server startup)
METRIC_FACTORY: MetricFactory = None


# ---------------------------------------------------------------------------
# Metrics Registry with Auto Exception Handling and Label Injection
# ---------------------------------------------------------------------------


class MetricsRegistry:
    """Metrics registry that auto-injects labels and handles exceptions."""

    def __init__(self, **context_labels):
        """Initialize registry with context labels."""
        self._context_labels = context_labels

    @property
    def context_labels(self):
        """Return a copy of the context labels."""
        return self._context_labels.copy()

    def with_labels(self, label_names, **extra_labels):
        """Extract a subset of context labels matching the given label names."""

        labels = {
            label: self._context_labels.get(label, "unknown")
            for label in label_names
            if label in self._context_labels
        }
        labels.update(extra_labels)
        return labels

    @contextmanager
    def _track_operation(
        self, operation_type, total_metric, duration_metric, skip_error_check=None
    ):
        """
        Common context manager for tracking operation metrics.

        Args:
            operation_type: Operation type label (or None for operations without this label)
            total_metric: Counter metric for total operations
            duration_metric: Histogram metric for operation duration
            skip_error_check: Optional callable(exception) -> bool that returns True
                            if the exception should skip metrics recording and re-raise
        """

        status = OperationStatus.SUCCESS
        record_metrics = True
        start_time = time.monotonic()

        # Prepare operation_type if provided
        operation_labels = {}
        if operation_type is not None:
            operation_labels["operation_type"] = operation_type

        try:
            yield
        except ProcessTimedOut:
            status = OperationStatus.TIMEOUT
            raise
        except ProcessExecutionError as exc:
            # Check if this error should skip metrics recording
            if skip_error_check and skip_error_check(exc):
                record_metrics = False
                raise
            status = OperationStatus.FAILURE
            raise
        finally:
            if record_metrics:
                # Build label subset for total_metric (includes status)
                total_labels = self.with_labels(
                    total_metric._labelnames, status=status.value, **operation_labels
                )
                total_metric.labels(**total_labels).inc()

                # Build label subset for duration_metric (no status)
                duration_labels = self.with_labels(
                    duration_metric._labelnames, **operation_labels
                )
                duration = time.monotonic() - start_time
                duration_metric.labels(**duration_labels).observe(duration)

    @contextmanager
    def mount(self, operation_type):
        """
        Context manager for mount operations with auto exception handling.

        Automatically:
        - Records counter with status label (success/failure/timeout)
        - Records duration histogram
        - Injects all context labels
        - Maps plumbum exceptions to status labels
        - Re-raises exceptions for CSI error handling

        Args:
            operation_type (str): Type of mount operation (nfs, block_mount, etc.)

        Raises:
            ProcessTimedOut: If mount times out
            ProcessExecutionError: If mount fails

        Usage:
            with registry.mount("nfs"):
                cmd.mount['-t', 'nfs', src, tgt].run(timeout=60)
        """
        with self._track_operation(
            operation_type,
            METRIC_FACTORY.mount_operations_total,
            METRIC_FACTORY.mount_duration_seconds,
        ):
            yield

    @contextmanager
    def umount(self, operation_type):
        """
        Context manager for unmount operations with auto exception handling.

        Note: Automatically skips metrics for "not mounted" errors (no-op cases).

        Args:
            operation_type (str): Type of unmount operation (nfs, block_mount, etc.)

        Raises:
            ProcessTimedOut: If unmount times out
            ProcessExecutionError: If unmount fails (including "not mounted")

        Usage:
            with registry.umount("nfs"):
                cmd.umount[path].run(timeout=60)
        """

        def skip_not_mounted(exc):
            """Skip metrics for 'not mounted' errors (no-op cases)."""
            return "not mounted" in exc.stderr

        with self._track_operation(
            operation_type,
            METRIC_FACTORY.umount_operations_total,
            METRIC_FACTORY.umount_duration_seconds,
            skip_error_check=skip_not_mounted,
        ):
            yield

    @contextmanager
    def nvme_connect(self):
        """
        Context manager for NVMe-oF connect operations.

        Usage:
            with registry.nvme_connect():
                connect_nvme_targets(discovery_server=..., host_nqn=...)
        """
        with self._track_operation(
            operation_type=None,  # NVMe metrics don't have operation_type label
            total_metric=METRIC_FACTORY.nvme_connect_operations_total,
            duration_metric=METRIC_FACTORY.nvme_connect_duration_seconds,
        ):
            yield

    @contextmanager
    def csi_operation(self, method_name):
        """Context manager for tracking CSI RPC operation metrics.

        Tracks execution time and status code (success/error) for CSI operations.
        """
        start_time = time.monotonic()
        exception = None

        try:
            yield
        except Exception as exc:
            # Capture exception for status code mapping
            exception = exc
            raise
        finally:
            duration = time.monotonic() - start_time
            grpc_status = get_grpc_status_code(exception)

            total_labels = self.with_labels(
                METRIC_FACTORY.csi_operations_total._labelnames,
                method_name=method_name,
                grpc_status_code=grpc_status,
            )
            duration_labels = self.with_labels(
                METRIC_FACTORY.csi_operations_seconds._labelnames,
                method_name=method_name,
                grpc_status_code=grpc_status,
            )

            METRIC_FACTORY.csi_operations_total.labels(**total_labels).inc()
            METRIC_FACTORY.csi_operations_seconds.labels(**duration_labels).observe(
                duration
            )


# ---------------------------------------------------------------------------
# Helper: Extract Labels from CSI Request (for future use)
# ---------------------------------------------------------------------------


def get_metrics_registry(params, hostname, driver_name):
    """
    Create a MetricsRegistry with labels extracted from CSI gRPC request context.

    This helper function extracts volume and snapshot identifiers from the CSI
    request parameters and creates a MetricsRegistry instance with all labels
    pre-configured.

    Args:
        params (dict): CSI request parameters containing:
            - volume_id (str): CSI volume ID (or 'name' for CreateVolume)
        hostname (str): Node hostname/ID (from CONF.node_id) - REQUIRED
        driver_name (str): CSI driver name (from CONF.plugin_name) - REQUIRED

    Returns:
        MetricsRegistry: Instance with pre-configured labels (uses "unknown" defaults if not present)

    Usage (in CSI gRPC method):
        def NodePublishVolume(self, request, context, metrics_registry):
            # metrics_registry is automatically injected via base.py
            # Use it with automatic label injection
            with metrics_registry.mount("nfs"):
                mount(src, tgt, ...)
    """

    labels = {
        "driver_name": driver_name,
        "hostname": hostname,
        # CreateVolume uses 'name', others use 'volume_id'
        "volume_id": params.get("volume_id") or params.get("name", "unknown"),
    }

    return MetricsRegistry(**labels)


# ================================================================
# NFS Transport (xprt) Statistics Parsing
# ================================================================


def _read_file_safe(path, timeout=1):
    """Read sysfs file safely using hostcmd.cat with timeout."""

    try:
        p = Path(path)
        if not p.exists():
            return None

        content = hostcmd.cat(str(p), timeout=timeout)
        # strip trailing whitespace and null bytes
        content = content.strip().rstrip('\x00').strip()
        return content if content else None

    except (ProcessTimedOut, ProcessExecutionError) as exc:
        logger.warning(f"Failed to read file {path}: {exc}")
        return None


def _parse_info_keyval(content):
    """Parse key=value lines (e.g. from xprt info file) into a dict."""
    result = {}
    for line in (content or "").split("\n"):
        if "=" in line:
            key, val = line.split("=", 1)
            result[key.strip()] = val.strip()
    return result


def _parse_state_flags(state_str):
    """Parse kernel state string into set of flags.

    Kernel format: "state=LOCKED CONNECTED BOUND" or "state=CLOSED"
    Returns: {"LOCKED", "CONNECTED", "BOUND"}
    """
    if not state_str or state_str == "UNKNOWN":
        return set()

    # Remove "state=" prefix if present
    if state_str.startswith("state="):
        state_str = state_str[6:]

    # Split and filter empty
    flags = {flag.strip() for flag in state_str.split() if flag.strip()}

    # Special case: "CLOSED" is a single state
    if state_str.strip() == "CLOSED":
        return {"CLOSED"}

    return flags


def _is_local_address(addr):
    """
    Check if address is localhost/loopback (should not be counted as CSI mount).
    
    Local transports can appear for:
    - System NFS mounts to localhost
    - Debugging/testing scenarios
    - Non-CSI mounts
    
    Args:
        addr: IP address or hostname (may include port)
            IPv4: "127.0.0.1" or "127.0.0.1:2049"
            IPv6: "::1" (no bracket notation in kernel xprt info)
            Note: kernel reports IPv6 as "::1" without brackets, even with port
    
    Returns:
        bool: True if address is local/loopback
    
    Note:
        Callers should filter out "unknown" addresses before calling this function.
        The check below is defensive only (prevents crashes if called incorrectly).
    """
    # Defensive check: unknown/empty addresses should be filtered earlier
    # If we get here, treat as non-local (but this shouldn't happen in normal flow)
    if not addr or addr == "unknown":
        return False
    
    # Strip port if present
    # IPv4: "127.0.0.1:2049" -> "127.0.0.1"
    # IPv6 is tricky: kernel may report "::1" without port, or "::1:2049" which is ambiguous
    # For safety, check before stripping
    clean_addr = addr
    if ':' in addr:
        # Check if it's a full IPv6 address (multiple colons)
        colon_count = addr.count(':')
        if colon_count == 1:
            # Single colon: likely "IP:port" (IPv4 or hostname)
            clean_addr = addr.rsplit(':', 1)[0]
        # else: multiple colons = IPv6 address, keep as-is (e.g., "::1")
    
    # Check common loopback addresses
    loopback_addrs = {
        '127.0.0.1',      # IPv4 loopback
        'localhost',      # hostname
        '::1',            # IPv6 loopback
        '0.0.0.0',        # Any/all interfaces (shouldn't appear in dstaddr, but check)
        '::',             # IPv6 any
    }
    
    # Case-insensitive check for hostname (handles "localhost", "LOCALHOST", "LocalHost", etc.)
    return clean_addr.lower() in loopback_addrs or clean_addr.startswith('127.')


def _is_transport_healthy(state_flags, pending, backlog):
    """Check if transport is healthy based on state and queue depths."""
    if "CONNECTED" not in state_flags:
        return False
    if (
        "OFFLINE" in state_flags
        or "CLOSING" in state_flags
        or "CLOSE_WAIT" in state_flags
    ):
        return False
    if "CONGESTED" in state_flags:
        return False
    if pending > 100 or backlog > 50:
        return False
    return True


def _read_xprt_state_and_flags(xprt_dir):
    """Read state file and return (raw_string, set of flags).
    
    Supports both kernel naming conventions:
    - Newer: 'state' file
    - Older: 'xprt_state' file
    """
    # Try newer kernel naming first
    state_raw = _read_file_safe(xprt_dir / "state")
    
    # Fallback to older kernel naming
    if not state_raw:
        state_raw = _read_file_safe(xprt_dir / "xprt_state")
    
    if not state_raw:
        state_raw = "UNKNOWN"
    
    return state_raw, _parse_state_flags(state_raw)


def _read_xprt_info(xprt_dir):
    """Read info file and return dict (srcaddr, dstaddr, etc.).
    
    Supports both kernel naming conventions:
    - Newer: 'info' file with key=value format
    - Older: Separate 'dstaddr', 'srcaddr', 'xprt_info' files
    
    Note: On older kernels, pending/backlog are in xprt_info as
    'pending_q_len' and 'backlog_q_len' instead of separate files.
    """
    # Try newer kernel naming: single 'info' file with key=value pairs
    info_raw = _read_file_safe(xprt_dir / "info")
    if info_raw:
        return _parse_info_keyval(info_raw)

    # Fallback to older kernel naming: separate files for each field
    info = {}
    
    # Read destination address
    dstaddr = _read_file_safe(xprt_dir / "dstaddr")
    if dstaddr:
        info["dstaddr"] = dstaddr.strip()

    # Read source address
    srcaddr = _read_file_safe(xprt_dir / "srcaddr")
    if srcaddr:
        info["srcaddr"] = srcaddr.strip()

    # Read xprt_info file (contains key=value pairs including pending_q_len, backlog_q_len)
    xprt_info_raw = _read_file_safe(xprt_dir / "xprt_info")
    if xprt_info_raw:
        info.update(_parse_info_keyval(xprt_info_raw))

    return info


def _read_xprt_queues(xprt_dir, info_dict=None):
    """Read pending and backlog queue depths.
    
    Supports both kernel naming conventions:
    - Newer: Separate 'pending' and 'backlog' files
    - Older: Values in xprt_info as 'pending_q_len' and 'backlog_q_len'
    
    Args:
        xprt_dir: Path to xprt directory
        info_dict: Optional dict from _read_xprt_info() to check for queue values
    
    Returns:
        Tuple of (pending, backlog)
    """
    pending = 0
    backlog = 0
    
    # Try newer kernel: separate files
    pending_raw = _read_file_safe(xprt_dir / "pending")
    backlog_raw = _read_file_safe(xprt_dir / "backlog")
    
    if pending_raw:
        try:
            pending = int(pending_raw.strip())
        except (ValueError, AttributeError):
            pending = 0
    
    if backlog_raw:
        try:
            backlog = int(backlog_raw.strip())
        except (ValueError, AttributeError):
            backlog = 0
    
    # If files don't exist, try older kernel: check info_dict for queue values
    if pending == 0 and backlog == 0 and info_dict:
        # Older kernels have these in xprt_info file
        if "pending_q_len" in info_dict:
            try:
                pending = int(info_dict["pending_q_len"])
            except (ValueError, TypeError):
                pass
        
        if "backlog_q_len" in info_dict:
            try:
                backlog = int(info_dict["backlog_q_len"])
            except (ValueError, TypeError):
                pass
    
    return pending, backlog


def _parse_single_xprt(xprt_dir):
    """Parse a single xprt directory and return stats dict, or None on skip/error."""
    match = re.match(r"xprt-(\d+)-(\w+)", xprt_dir.name)
    if not match:
        return None

    try:
        _xprt_id, protocol = match.groups()

        #  Check state first - if CLOSED, skip immediately without reading other files
        state_raw, state_flags = _read_xprt_state_and_flags(xprt_dir)
        if "CLOSED" in state_flags:
            return None

        # read dstaddr early to check for loopback before reading other files
        dstaddr = _read_file_safe(xprt_dir / "dstaddr")
        if dstaddr:
            dstaddr = dstaddr.strip()

        if not dstaddr:
            return None

        if _is_local_address(dstaddr):
            return None

        # continue: non-closed, non-loopback transports
        info = _read_xprt_info(xprt_dir)
        info["dstaddr"] = dstaddr

        pending, backlog = _read_xprt_queues(xprt_dir, info)
    except (OSError, ValueError) as e:
        logger.warning(f"Failed to parse {xprt_dir.name}: {e}")
        return None

    is_healthy = _is_transport_healthy(state_flags, pending, backlog)
    return {
        "id": f"{xprt_dir.parent.name}/{xprt_dir.name}",
        "protocol": protocol,
        "local_addr": info.get("srcaddr", "unknown"),
        "remote_addr": dstaddr,
        "state": state_raw,
        "state_flags": list(state_flags),
        "pending": pending,
        "backlog": backlog,
        "healthy": is_healthy,
    }


def collect_xprt_stats():
    """Collect all xprt statistics from sysfs.

    Uses a producer/consumer: the producer enumerates xprt
    directories and feeds them into a queue; worker threads parse each
    xprt in parallel (sysfs reads can block on kernel locks, so
    concurrency keeps overall latency low).

    Returns:
        dict: Summary and detailed statistics
    """
    base_path = Path("/sys/kernel/sunrpc/xprt-switches")

    if not base_path.exists():
        # Not on Linux or NFS not loaded
        return {
            "summary": {
                "total": 0,
                "connected": 0,
                "unhealthy": 0,
                "pending_total": 0,
                "backlog_total": 0,
            },
            "transports": [],
        }

    all_transports = []
    lock = threading.Lock()
    work_queue = queue.Queue()

    def worker(worker_id):
        """Consumer: pull xprt dirs from the queue and parse them."""
        while True:
            xprt_dir = work_queue.get()
            if xprt_dir is None:
                break
            try:
                xprt_data = _parse_single_xprt(xprt_dir)
                if xprt_data:
                    with lock:
                        all_transports.append(xprt_data)
            except Exception as e:
                logger.warning(f"Worker-{worker_id} failed on {xprt_dir}: {e}")
            finally:
                work_queue.task_done()

    # Start worker threads
    workers = []
    for i in range(XPRT_WORKERS):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        t.start()
        workers.append(t)

    enqueued = 0
    # Producer: enumerate xprt directories and feed the queue
    for switch_dir in sorted(base_path.glob("switch-*")):
        for xprt_dir in sorted(switch_dir.glob("xprt-*")):
            work_queue.put(xprt_dir)
            enqueued += 1

    # Wait for all items to be processed
    work_queue.join()
    # Signal workers to exit
    for _ in workers:
        # the timeout here indicates that the worker thread is blocked.
        work_queue.put(None, timeout=2)

    # Calculate summary
    total = len(all_transports)
    connected = sum(1 for x in all_transports if "CONNECTED" in x["state_flags"])
    unhealthy = sum(1 for x in all_transports if not x["healthy"])
    pending_total = sum(x["pending"] for x in all_transports)
    backlog_total = sum(x["backlog"] for x in all_transports)

    return {
        "summary": {
            "total": total,
            "connected": connected,
            "unhealthy": unhealthy,
            "pending_total": pending_total,
            "backlog_total": backlog_total,
        },
        "transports": all_transports,
    }


# Track active destinations to detect removed transports
_xprt_previous_destinations = set()


def _count_nfs_mounts_per_destination():
    """Count NFS mounts per destination IP from /proc/self/mountinfo.

    Parses mount info to find NFS mounts and counts how many mounts
    each NFS server IP is handling. This provides visibility into
    transport utilization (one transport can serve multiple mounts).

    Returns:
        dict: Mapping of destination IP to mount count, e.g. {"172.21.112.4": 2, "172.21.112.3": 1}
    """

    counts = CollCounter()
    try:
        for mount in MountInfo.from_host():
            # NFS mounts have fs_type "nfs", "nfs4", etc. and mount_source like "172.21.112.4:/path"
            if mount.fs_type.startswith("nfs") and mount.server_ip:
                if mount.mount_point.startswith(str(hostcmd.HOST_MOUNT)):
                    continue
                counts[mount.server_ip] += 1
    except Exception as e:
        logger.warning(f"Failed to count NFS mounts: {e}")

    return dict(counts)


def update_xprt_metrics():
    """Update Prometheus xprt metrics from current sysfs state."""
    global _xprt_previous_destinations
    
    try:
        stats = collect_xprt_stats()
        summary = stats["summary"]

        # Update aggregate metrics (always visible, even when 0)
        METRIC_FACTORY.xprt_total.set(summary["total"])
        METRIC_FACTORY.xprt_connected.set(summary["connected"])
        METRIC_FACTORY.xprt_pending_total.set(summary["pending_total"])
        METRIC_FACTORY.xprt_backlog_total.set(summary["backlog_total"])
        METRIC_FACTORY.xprt_unhealthy.set(summary["unhealthy"])

        # Track current destinations
        current_destinations = set()

        # Update per-transport metrics with VIP label
        for transport in stats["transports"]:
            # Extract destination IP (strip port if present)
            dest = transport["remote_addr"]
            if ":" in dest:
                dest = dest.rsplit(":", 1)[0]  # Remove port, keep IPv6 safe

            current_destinations.add(dest)

            state_flags = set(transport["state_flags"])

            # Connected state: both CONNECTED and BOUND flags must be set
            is_connected = "CONNECTED" in state_flags and "BOUND" in state_flags
            METRIC_FACTORY.xprt_connected_per_dest.labels(destination=dest).set(
                1 if is_connected else 0
            )

            # Congested state: either CONGESTED or CWND_WAIT
            is_congested = "CONGESTED" in state_flags or "CWND_WAIT" in state_flags
            METRIC_FACTORY.xprt_congested.labels(destination=dest).set(
                1 if is_congested else 0
            )

            # Locked state
            is_locked = "LOCKED" in state_flags
            METRIC_FACTORY.xprt_locked.labels(destination=dest).set(
                1 if is_locked else 0
            )

            # Queue depths
            METRIC_FACTORY.xprt_pending_requests.labels(destination=dest).set(
                transport["pending"]
            )
            METRIC_FACTORY.xprt_backlog_depth.labels(destination=dest).set(
                transport["backlog"]
            )

        # Count NFS mounts per destination IP from /proc/self/mountinfo
        mount_counts = _count_nfs_mounts_per_destination()
        for dest in current_destinations:
            METRIC_FACTORY.xprt_mounts.labels(destination=dest).set(
                mount_counts.get(dest, 0)
            )

        # When a transport is removed, completely remove its metric label combinations
        removed_destinations = _xprt_previous_destinations - current_destinations
        for dest in removed_destinations:
            try:
                # Access internal _metrics dict to remove label combinations
                # Label values must be passed as a tuple
                METRIC_FACTORY.xprt_connected_per_dest._metrics.pop((dest,))
                METRIC_FACTORY.xprt_congested._metrics.pop((dest,))
                METRIC_FACTORY.xprt_locked._metrics.pop((dest,))
                METRIC_FACTORY.xprt_pending_requests._metrics.pop((dest,))
                METRIC_FACTORY.xprt_backlog_depth._metrics.pop((dest,))
                METRIC_FACTORY.xprt_mounts._metrics.pop((dest,))
                logger.debug("Removed metrics for disappeared destination: %s", dest)
            except KeyError:
                # Label combination may not exist (e.g., first run after restart)
                pass

        # Update tracking set for next iteration
        _xprt_previous_destinations = current_destinations

    except Exception as e:
        logger.warning(f"Failed to update xprt metrics: {e}")


# ================================================================
# HTTP Server with Custom Endpoints
# ================================================================


class MetricsHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for /metrics and /health endpoints."""

    # Class variable to store whether this is a node service
    collect_xprt_metrics = False

    def log_message(self, format, *args):
        """Use our logger instead of stderr."""
        logger.debug(f"HTTP {self.client_address[0]}: {format % args}")

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/metrics":
            self._serve_prometheus_metrics()
        elif self.path in ["/health", "/healthz"]:
            self._serve_health()
        else:
            self.send_error(404, "Not Found")

    def _serve_prometheus_metrics(self):
        """Serve Prometheus metrics."""
        try:
            logger.info("HTTP request for /metrics received")
            # Update xprt metrics only on CSI node (not controller-only)
            if self.collect_xprt_metrics:
                update_xprt_metrics()

            # Generate Prometheus format
            metrics = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(metrics)
            logger.info("Metrics sent successfully")
        except Exception as e:
            logger.error(f"Failed to serve metrics: {e}")
            self.send_error(500, str(e))

    def _serve_health(self):
        """Serve health check endpoint (e.g. for Kubernetes liveness/readiness probes)."""
        response = json.dumps({"status": "ok"})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.encode("utf-8"))


def start_metrics_server(port=9090, addr="0.0.0.0", is_node_service=False, collect_nfs_xprt=True):
    """
    Start the metrics HTTP server with Prometheus endpoints.

    When metrics are enabled, failure to start the server is fatal: the error
    is propagated so the process (e.g. CSI node pod) does not run with metrics
    disabled unexpectedly.

    Args:
        port (int): Port to expose metrics on (default: 9090)
        addr (str): Address to bind to (default: 0.0.0.0, all interfaces)
        is_node_service (bool): True for node service (DaemonSet), False for controller
        collect_nfs_xprt (bool): True to collect NFS transport metrics, False to disable
                                 (default: True for NFS driver, set False for block driver)
                                Determines which metrics are registered and whether xprt stats are collected

    Raises:
        OSError: If the server cannot bind (e.g. port in use).

    Endpoints:
        /metrics - Prometheus metrics (mount/unmount + NFS transport stats)
        /health  - Health check (Kubernetes liveness/readiness)
    """

    global METRIC_FACTORY
    METRIC_FACTORY = MetricFactory(is_node_service)

    # Configure xprt metrics collection (only for node services with NFS)
    # Block driver should set collect_nfs_xprt=False since it doesn't use NFS
    MetricsHTTPHandler.collect_xprt_metrics = is_node_service and collect_nfs_xprt

    server = HTTPServer((addr, port), MetricsHTTPHandler)
    server_thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
        name="metrics-server",
    )
    server_thread.start()

    logger.info("Metrics server started on %s:%s", addr, port)
    logger.info("  - Prometheus: http://%s:%s/metrics", addr, port)
    logger.info("  - Health: http://%s:%s/health", addr, port)
