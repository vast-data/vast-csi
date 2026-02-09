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
Metrics module for CSI Node operations.

This module provides Prometheus metrics for tracking mount/unmount operations
in the CSI driver, including:
- Operation counters (mount/unmount success and failures)
- Operation duration histograms (mount/unmount times)
- Timeout counters
- NFS transport (xprt) statistics

Endpoints:
- /metrics - Prometheus metrics (mount/unmount + NFS transport stats)
- /health  - Health check endpoint
"""

import json  
import re
import time
from contextlib import contextmanager
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from vast_csi.logging import logger


mount_operations_total = Counter(
    'csi_node_mount_operations_total',
    'Total number of mount operations',
    ['operation_type', 'status']  # operation_type: nfs|block_mount, status: success|failure|timeout
)

mount_duration_seconds = Histogram(
    'csi_node_mount_duration_seconds',
    'Duration of mount operations in seconds',
    ['operation_type'],  # operation_type: nfs|block_mount
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf'))
)

# NVMe-oF connect metrics (separate from mount; connect is not a mount operation)
nvme_connect_operations_total = Counter(
    'csi_node_nvme_connect_operations_total',
    'Total number of NVMe-oF connect operations',
    ['status']  # status: success|failure
)

nvme_connect_duration_seconds = Histogram(
    'csi_node_nvme_connect_duration_seconds',
    'Duration of NVMe-oF connect operations in seconds',
    [],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf'))
)

# Unmount operation metrics
umount_operations_total = Counter(
    'csi_node_umount_operations_total',
    'Total number of unmount operations',
    ['operation_type', 'status']  # operation_type: nfs|block_mount, status: success|failure|timeout
)

umount_duration_seconds = Histogram(
    'csi_node_umount_duration_seconds',
    'Duration of unmount operations in seconds',
    ['operation_type'],  # operation_type: nfs|block_mount
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf'))
)


# ---------------------------------------------------------------------------
# Context managers to record operation metrics (reduces boilerplate at call sites)
# ---------------------------------------------------------------------------

class _MountRecorder:
    """Records outcome and duration for a single mount operation."""

    def __init__(self, operation_type, start_time):
        self._operation_type = operation_type
        self._start_time = start_time
        self._status = None  # success | timeout | failure

    def success(self):
        self._status = "success"
        mount_operations_total.labels(operation_type=self._operation_type, status="success").inc()

    def timeout(self):
        self._status = "timeout"
        mount_operations_total.labels(operation_type=self._operation_type, status="timeout").inc()

    def failure(self):
        self._status = "failure"
        mount_operations_total.labels(operation_type=self._operation_type, status="failure").inc()

    def observe_duration(self):
        if self._status is not None:
            mount_duration_seconds.labels(operation_type=self._operation_type).observe(
                time.monotonic() - self._start_time
            )


class _UmountRecorder:
    """Records outcome and duration for a single umount operation."""

    def __init__(self, operation_type, start_time):
        self._operation_type = operation_type
        self._start_time = start_time
        self._status = None  # success | timeout | failure | skip (no-op, e.g. not mounted)

    def success(self):
        self._status = "success"
        umount_operations_total.labels(operation_type=self._operation_type, status="success").inc()

    def timeout(self):
        self._status = "timeout"
        umount_operations_total.labels(operation_type=self._operation_type, status="timeout").inc()

    def failure(self):
        self._status = "failure"
        umount_operations_total.labels(operation_type=self._operation_type, status="failure").inc()

    def skip(self):
        """No-op outcome (e.g. path not mounted); do not record duration."""
        self._status = "skip"

    def observe_duration(self):
        if self._status not in (None, "skip"):
            umount_duration_seconds.labels(operation_type=self._operation_type).observe(
                time.monotonic() - self._start_time
            )


@contextmanager
def record_mount(operation_type):
    """
    Context manager to record mount operation metrics.
    Call rec.success(), rec.timeout(), or rec.failure() in the appropriate branch.
    Duration is observed on exit.
    """
    rec = _MountRecorder(operation_type, time.monotonic())
    try:
        yield rec
    finally:
        rec.observe_duration()


@contextmanager
def record_umount(operation_type):
    """
    Context manager to record umount operation metrics.
    Call rec.success(), rec.timeout(), rec.failure(), or rec.skip() (for not-mounted no-op).
    Duration is observed on exit unless rec.skip() was used.
    """
    rec = _UmountRecorder(operation_type, time.monotonic())
    try:
        yield rec
    finally:
        rec.observe_duration()


class _NVMeConnectRecorder:
    """Records outcome and duration for a single NVMe-oF connect operation."""

    def __init__(self, start_time):
        self._start_time = start_time
        self._status = None  # success | failure

    def success(self):
        self._status = "success"
        nvme_connect_operations_total.labels(status="success").inc()

    def failure(self):
        self._status = "failure"
        nvme_connect_operations_total.labels(status="failure").inc()

    def observe_duration(self):
        if self._status is not None:
            nvme_connect_duration_seconds.observe(time.monotonic() - self._start_time)


@contextmanager
def record_nvme_connect():
    """
    Context manager to record NVMe-oF connect operation metrics.
    Call rec.success() or rec.failure(). Duration is observed on exit.
    """
    rec = _NVMeConnectRecorder(time.monotonic())
    try:
        yield rec
    finally:
        rec.observe_duration()


# NFS transport (xprt) metrics
xprt_total = Gauge(
    'csi_node_nfs_xprt_total',
    'Total number of NFS transports'
)

xprt_connected = Gauge(
    'csi_node_nfs_xprt_connected',
    'Number of NFS transports in CONNECTED state'
)

xprt_pending_total = Gauge(
    'csi_node_nfs_xprt_pending_requests_total',
    'Total pending RPC requests across all transports'
)

xprt_backlog_total = Gauge(
    'csi_node_nfs_xprt_backlog_total',
    'Total backlog queue depth across all transports'
)

xprt_unhealthy = Gauge(
    'csi_node_nfs_xprt_unhealthy',
    'Number of transports with potential issues'
)

# Per-transport metrics with VIP label
xprt_connected = Gauge(
    'csi_node_nfs_xprt_connected_state',
    'Transport is connected (CONNECTED and BOUND flags set)',
    ['destination']  # VIP/destination IP
)

xprt_congested = Gauge(
    'csi_node_nfs_xprt_congested_state',
    'Transport is congested (CONGESTED or CWND_WAIT flags set)',
    ['destination']
)

xprt_locked = Gauge(
    'csi_node_nfs_xprt_locked_state',
    'Transport is locked (LOCKED flag set)',
    ['destination']
)

xprt_pending_requests = Gauge(
    'csi_node_nfs_xprt_pending_requests',
    'Number of pending RPC requests for this transport',
    ['destination']
)

xprt_backlog_depth = Gauge(
    'csi_node_nfs_xprt_backlog_depth',
    'Backlog queue depth for this transport',
    ['destination']
)


# ================================================================
# NFS Transport (xprt) Statistics Parsing
# ================================================================

def _read_file_safe(path):
    """Read file safely, return None on error."""
    try:
        p = Path(path)
        return p.read_text().strip() if p.exists() else None
    except OSError:
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


def _is_transport_healthy(state_flags, pending, backlog):
    """Check if transport is healthy based on state and queue depths."""
    if "CONNECTED" not in state_flags:
        return False
    if "OFFLINE" in state_flags or "CLOSING" in state_flags or "CLOSE_WAIT" in state_flags:
        return False
    if "CONGESTED" in state_flags:
        return False
    if pending > 100 or backlog > 50:
        return False
    return True


def _read_xprt_state_and_flags(xprt_dir):
    """Read state file and return (raw_string, set of flags)."""
    state_raw = _read_file_safe(xprt_dir / "state") or "UNKNOWN"
    return state_raw, _parse_state_flags(state_raw)


def _read_xprt_info(xprt_dir):
    """Read info file and return dict (srcaddr, dstaddr, etc.)."""
    info_raw = _read_file_safe(xprt_dir / "info") or ""
    return _parse_info_keyval(info_raw)


def _read_xprt_queues(xprt_dir):
    """Read pending and backlog files; return (pending, backlog)."""
    pending_raw = _read_file_safe(xprt_dir / "pending") or "0"
    backlog_raw = _read_file_safe(xprt_dir / "backlog") or "0"
    return int(pending_raw), int(backlog_raw)


def _parse_single_xprt(xprt_dir):
    """Parse a single xprt directory and return stats dict, or None on skip/error."""
    match = re.match(r"xprt-(\d+)-(\w+)", xprt_dir.name)
    if not match:
        return None

    try:
        _xprt_id, protocol = match.groups()
        state_raw, state_flags = _read_xprt_state_and_flags(xprt_dir)
        info = _read_xprt_info(xprt_dir)
        pending, backlog = _read_xprt_queues(xprt_dir)
    except (OSError, ValueError) as e:
        logger.info("Failed to parse xprt %s: %s", xprt_dir, e)
        return None

    is_healthy = _is_transport_healthy(state_flags, pending, backlog)
    return {
        "id": f"{xprt_dir.parent.name}/{xprt_dir.name}",
        "protocol": protocol,
        "local_addr": info.get("srcaddr", "unknown"),
        "remote_addr": info.get("dstaddr", "unknown"),
        "state": state_raw,
        "state_flags": list(state_flags),
        "pending": pending,
        "backlog": backlog,
        "healthy": is_healthy,
    }


def collect_xprt_stats():
    """Collect all xprt statistics from sysfs.
    
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
                "backlog_total": 0
            },
            "transports": []
        }
    
    all_transports = []
    
    try:
        # Iterate switches and xprts
        for switch_dir in sorted(base_path.glob("switch-*")):
            for xprt_dir in sorted(switch_dir.glob("xprt-*")):
                xprt_data = _parse_single_xprt(xprt_dir)
                if xprt_data:
                    all_transports.append(xprt_data)
    except Exception as e:
        logger.warning(f"Failed to collect xprt stats: {e}")
    
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
            "backlog_total": backlog_total
        },
        "transports": all_transports
    }


def update_xprt_metrics():
    """Update Prometheus xprt metrics from current sysfs state."""
    try:
        stats = collect_xprt_stats()
        summary = stats["summary"]
        
        # Update aggregate metrics
        xprt_total.set(summary["total"])
        xprt_connected.set(summary["connected"])
        xprt_pending_total.set(summary["pending_total"])
        xprt_backlog_total.set(summary["backlog_total"])
        xprt_unhealthy.set(summary["unhealthy"])
        
        # Update per-transport metrics with VIP label
        for transport in stats["transports"]:
            # Extract destination IP (strip port if present)
            dest = transport["remote_addr"]
            if ':' in dest:
                dest = dest.rsplit(':', 1)[0]  # Remove port, keep IPv6 safe
            
            state_flags = set(transport["state_flags"])
            
            # Connected state: both CONNECTED and BOUND must be present
            is_connected = "CONNECTED" in state_flags and "BOUND" in state_flags
            xprt_connected.labels(destination=dest).set(1 if is_connected else 0)
            
            # Congested state: either CONGESTED or CWND_WAIT
            is_congested = "CONGESTED" in state_flags or "CWND_WAIT" in state_flags
            xprt_congested.labels(destination=dest).set(1 if is_congested else 0)
            
            # Locked state
            is_locked = "LOCKED" in state_flags
            xprt_locked.labels(destination=dest).set(1 if is_locked else 0)
            
            # Queue depths
            xprt_pending_requests.labels(destination=dest).set(transport["pending"])
            xprt_backlog_depth.labels(destination=dest).set(transport["backlog"])
            
    except Exception as e:
        logger.warning(f"Failed to update xprt metrics: {e}")


# ================================================================
# HTTP Server with Custom Endpoints
# ================================================================

class MetricsHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for /metrics and /health endpoints."""
    
    def log_message(self, format, *args):
        """Use our logger instead of stderr."""
        logger.debug(f"HTTP {self.client_address[0]}: {format % args}")
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/metrics':
            self._serve_prometheus_metrics()
        elif self.path in ['/health', '/healthz']:
            self._serve_health()
        else:
            self.send_error(404, "Not Found")
    
    def _serve_prometheus_metrics(self):
        """Serve Prometheus metrics."""
        try:
            # Update xprt metrics on-demand when scraped
            update_xprt_metrics()
            
            # Generate Prometheus format
            metrics = generate_latest()
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.end_headers()
            self.wfile.write(metrics)
        except Exception as e:
            logger.error(f"Failed to serve metrics: {e}")
            self.send_error(500, str(e))
    
    def _serve_health(self):
        """Serve health check endpoint (e.g. for Kubernetes liveness/readiness probes)."""
        response = json.dumps({"status": "ok"})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))


def start_metrics_server(port=9090, addr='0.0.0.0'):
    """
    Start the metrics HTTP server with Prometheus endpoints.

    When metrics are enabled, failure to start the server is fatal: the error
    is propagated so the process (e.g. CSI node pod) does not run with metrics
    disabled unexpectedly.

    Args:
        port (int): Port to expose metrics on (default: 9090)
        addr (str): Address to bind to (default: 0.0.0.0, all interfaces)

    Raises:
        OSError: If the server cannot bind (e.g. port in use).

    Endpoints:
        /metrics - Prometheus metrics (mount/unmount + NFS transport stats)
        /health  - Health check (Kubernetes liveness/readiness)
    """
    import threading

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
