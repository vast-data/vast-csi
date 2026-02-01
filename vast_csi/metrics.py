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
"""

from prometheus_client import Counter, Histogram, start_http_server
from vast_csi.logging import logger


# Mount operation metrics
mount_operations_total = Counter(
    'csi_node_mount_operations_total',
    'Total number of mount operations',
    ['operation_type', 'status']  # operation_type: nfs|block, status: success|failure|timeout
)

mount_duration_seconds = Histogram(
    'csi_node_mount_duration_seconds',
    'Duration of mount operations in seconds',
    ['operation_type'],  # operation_type: nfs|block
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf'))
)

# Unmount operation metrics
umount_operations_total = Counter(
    'csi_node_umount_operations_total',
    'Total number of unmount operations',
    ['operation_type', 'status']  # operation_type: nfs|block, status: success|failure|timeout
)

umount_duration_seconds = Histogram(
    'csi_node_umount_duration_seconds',
    'Duration of unmount operations in seconds',
    ['operation_type'],  # operation_type: nfs|block
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, float('inf'))
)


def start_metrics_server(port=9090, addr='0.0.0.0'):
    """
    Start the Prometheus metrics HTTP server.
    
    Args:
        port (int): Port to expose metrics on (default: 9090)
        addr (str): Address to bind to (default: 0.0.0.0)
    
    Returns:
        bool: True if server started successfully, False otherwise
    
    Note:
        If port is already in use, logs a warning and returns False.
        CSI driver continues without metrics in this case.
    """
    try:
        start_http_server(port, addr=addr)
        logger.info(f"Metrics server started on {addr}:{port}")
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
