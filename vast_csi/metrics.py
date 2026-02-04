# Copyright 2024 VAST Data Inc.
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
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from vast_csi.logging import logger


# Mount operation metrics
mount_operations_total = Counter(
    'csi_node_mount_operations_total',
    'Total number of mount operations',
    ['operation_type', 'status']  # operation_type: nfs|nvme_connect|block_mount, status: success|failure|timeout
)

mount_duration_seconds = Histogram(
    'csi_node_mount_duration_seconds',
    'Duration of mount operations in seconds',
    ['operation_type'],  # operation_type: nfs|nvme_connect|block_mount
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
        return Path(path).read_text().strip() if Path(path).exists() else None
    except Exception:
        return None


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


def _parse_single_xprt(xprt_dir):
    """Parse a single xprt directory and return stats dict."""
    try:
        # Extract xprt info
        match = re.match(r'xprt-(\d+)-(\w+)', xprt_dir.name)
        if not match:
            return None
        
        xprt_id, protocol = match.groups()
        
        # Read state
        state_raw = _read_file_safe(xprt_dir / "state") or "UNKNOWN"
        state_flags = _parse_state_flags(state_raw)
        
        # Read info for addresses
        info_raw = _read_file_safe(xprt_dir / "info") or ""
        info = {}
        for line in info_raw.split('\n'):
            if '=' in line:
                key, val = line.split('=', 1)
                info[key.strip()] = val.strip()
        
        # Read queue depths
        pending = int(_read_file_safe(xprt_dir / "pending") or "0")
        backlog = int(_read_file_safe(xprt_dir / "backlog") or "0")
        
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
            "healthy": is_healthy
        }
    except Exception as e:
        logger.debug(f"Failed to parse xprt {xprt_dir}: {e}")
        return None


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
        """Serve health check endpoint."""
        response = json.dumps({"status": "ok"})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))


def start_metrics_server(port=9090, addr='0.0.0.0'):
    """
    Start the metrics HTTP server with Prometheus endpoints.
    
    Args:
        port (int): Port to expose metrics on (default: 9090)
        addr (str): Address to bind to (default: 0.0.0.0)
    
    Returns:
        bool: True if server started successfully, False otherwise
    
    Endpoints:
        /metrics - Prometheus metrics (mount/unmount + NFS transport stats)
        /health  - Health check
    
    Note:
        If port is already in use, logs a warning and returns False.
        CSI driver continues without metrics in this case.
        
        NFS transport (xprt) metrics are parsed on-demand when /metrics is scraped.
    """
    try:
        import threading
        
        server = HTTPServer((addr, port), MetricsHTTPHandler)
        
        # Run server in background daemon thread
        server_thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="metrics-server"
        )
        server_thread.start()
        
        logger.info(f"Metrics server started on {addr}:{port}")
        logger.info(f"  - Prometheus: http://{addr}:{port}/metrics")
        logger.info(f"  - Health: http://{addr}:{port}/health")
        return True
        
    except OSError as e:
        if "Address already in use" in str(e) or "address already in use" in str(e).lower():
            logger.warning(f"Metrics port {port} already in use. Metrics will not be available. Error: {e}")
            return False
        logger.error(f"Failed to start metrics server due to OS error: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")
        return False
