# CSI Driver Metrics Reference

This guide provides a complete reference of all Prometheus metrics exposed by the VAST CSI driver, including what each metric means, when you'll see it, and example label values.

**Target Audience:** QA, DevOps, SRE teams monitoring CSI driver operations.

---

## Table of Contents

1. [Mount Operation Metrics](#mount-operation-metrics)
2. [Unmount Operation Metrics](#unmount-operation-metrics)
3. [NVMe-oF Connect Metrics](#nvme-of-connect-metrics)
4. [NFS Transport (xprt) Metrics](#nfs-transport-xprt-metrics)
5. [Understanding Labels](#understanding-labels)
6. [Common Scenarios and Expected Metrics](#common-scenarios-and-expected-metrics)

---

## Mount Operation Metrics

### `csi_node_mount_operations_total`

**Type:** Counter  
**Description:** Total number of mount operations performed by the CSI node.  
**When you see it:** Every time a PVC is mounted to a pod (NodePublishVolume call).

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `operation_type` | Type of mount operation | `nfs`, `block_mount`, `bind_mount` |
| `status` | Outcome of the operation | `success`, `failure`, `timeout` |
| `node_name` | Kubernetes node where mount happened | `worker-node-1`, `k8s-worker-02` |
| `pvc_namespace` | Namespace of the PVC being mounted | `default`, `prod`, `dev-team-a` |

**Example Metrics:**

```promql
# Successful NFS mount in 'prod' namespace on worker-node-1
csi_node_mount_operations_total{operation_type="nfs",status="success",node_name="worker-node-1",pvc_namespace="prod"} 15

# Failed block mount in 'default' namespace
csi_node_mount_operations_total{operation_type="block_mount",status="failure",node_name="worker-node-2",pvc_namespace="default"} 2

# Timeout during NFS mount
csi_node_mount_operations_total{operation_type="nfs",status="timeout",node_name="worker-node-1",pvc_namespace="dev"} 1
```

**What it means:**
- `status="success"` - Mount completed successfully, volume is ready for pod to use
- `status="failure"` - Mount failed (e.g., network issue, permission denied, invalid export)
- `status="timeout"` - Mount took longer than configured timeout (default: 30s)

**When to investigate:**
- If `status="failure"` or `status="timeout"` are increasing
- If certain namespaces have consistently higher failure rates
- If specific nodes show mount issues

---

### `csi_node_mount_duration_seconds`

**Type:** Histogram  
**Description:** Duration of mount operations in seconds (from start of mount command to completion).  
**When you see it:** Recorded for every mount operation (success, failure, or timeout).

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `operation_type` | Type of mount operation | `nfs`, `block_mount`, `bind_mount` |
| `node_name` | Kubernetes node | `worker-node-1`, `k8s-worker-02` |
| `pvc_namespace` | PVC namespace | `default`, `prod`, `dev-team-a` |

**Buckets:** 1s, 5s, 20s, +Inf (ranges: 0-1s, 1-5s, 5-20s, 20s+)

**Example Metrics:**

```promql
# Mount duration histogram for NFS mounts in 'prod' namespace
csi_node_mount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="1.0"} 12
csi_node_mount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="5.0"} 15
csi_node_mount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="20.0"} 15
csi_node_mount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="+Inf"} 15
csi_node_mount_duration_seconds_sum{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod"} 23.5
csi_node_mount_duration_seconds_count{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod"} 15
```

**What it means:**
- `le="1.0"` shows how many mounts completed within 1 second (fast)
- `le="5.0"` shows how many completed within 5 seconds (normal)
- `le="20.0"` shows how many completed within 20 seconds (slow)
- `_sum / _count` gives average mount duration

**Typical values:**
- **NFS mount:** 0.5-2 seconds (fast), 2-5 seconds (normal), 5-20 seconds (slow), >20 seconds (timeout/issue)
- **Block mount:** <1 second (fast)
- **Bind mount:** <1 second (very fast)

**When to investigate:**
- If average mount duration > 5 seconds consistently
- If many mounts are in the 30s+ buckets (near timeout)
- If mount duration increases over time (performance degradation)

---

## Unmount Operation Metrics

### `csi_node_umount_operations_total`

**Type:** Counter  
**Description:** Total number of unmount operations performed by the CSI node.  
**When you see it:** Every time a PVC is unmounted from a pod (NodeUnpublishVolume call).

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `operation_type` | Type of unmount operation | `nfs`, `block_mount`, `bind_mount` |
| `status` | Outcome of the operation | `success`, `failure`, `timeout` |
| `node_name` | Kubernetes node | `worker-node-1`, `k8s-worker-02` |
| `pvc_namespace` | PVC namespace | `default`, `prod`, `dev-team-a` |

**Example Metrics:**

```promql
# Successful NFS unmount
csi_node_umount_operations_total{operation_type="nfs",status="success",node_name="worker-node-1",pvc_namespace="prod"} 10

# Failed unmount (e.g., device busy)
csi_node_umount_operations_total{operation_type="nfs",status="failure",node_name="worker-node-1",pvc_namespace="prod"} 1

# Timeout during unmount
csi_node_umount_operations_total{operation_type="nfs",status="timeout",node_name="worker-node-1",pvc_namespace="prod"} 0
```

**What it means:**
- `status="success"` - Unmount completed, volume is detached from node
- `status="failure"` - Unmount failed (e.g., device busy, stale file handle)
- `status="timeout"` - Unmount took longer than configured timeout

**Special case:**
- "not mounted" errors are **NOT** counted as failures (CSI requires idempotency)

**When to investigate:**
- If `status="failure"` is increasing (may indicate pods not cleaning up properly)
- If unmount failures correlate with specific applications (file handles not closed)

---

### `csi_node_umount_duration_seconds`

**Type:** Histogram  
**Description:** Duration of unmount operations in seconds.  
**When you see it:** Recorded for every successful unmount operation.

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `operation_type` | Type of unmount operation | `nfs`, `block_mount`, `bind_mount` |
| `node_name` | Kubernetes node | `worker-node-1`, `k8s-worker-02` |
| `pvc_namespace` | PVC namespace | `default`, `prod`, `dev-team-a` |

**Buckets:** Same as mount duration (0.1s to 600s)

**Example Metrics:**

```promql
# Unmount duration histogram
csi_node_umount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="1.0"} 10
csi_node_umount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="5.0"} 10
csi_node_umount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="20.0"} 10
csi_node_umount_duration_seconds_bucket{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod",le="+Inf"} 10
csi_node_umount_duration_seconds_sum{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod"} 8.2
csi_node_umount_duration_seconds_count{operation_type="nfs",node_name="worker-node-1",pvc_namespace="prod"} 10
```

**Typical values:**
- **NFS unmount:** <1 second (fast), 1-5 seconds (normal), >5 seconds (slow)
- **Block unmount:** <1 second (fast)
- **Bind unmount:** <1 second (very fast)

**When to investigate:**
- If unmount duration > 5 seconds (may indicate hung NFS operations)
- If unmount takes longer than mount (unusual, may indicate storage issues)

---

## NVMe-oF Connect Metrics

### `csi_node_nvme_connect_operations_total`

**Type:** Counter  
**Description:** Total number of NVMe-oF connect operations (block driver only).  
**When you see it:** During volume attachment, when connecting to NVMe-oF targets.

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `status` | Outcome of the operation | `success`, `failure` |
| `node_name` | Kubernetes node | `worker-node-1`, `k8s-worker-02` |

**Note:** No `pvc_namespace` label because NVMe connect happens during staging (before NodePublishVolume where PVC info is available).

**Example Metrics:**

```promql
# Successful NVMe connect
csi_node_nvme_connect_operations_total{status="success",node_name="worker-node-1"} 5

# Failed NVMe connect
csi_node_nvme_connect_operations_total{status="failure",node_name="worker-node-1"} 1
```

**What it means:**
- `status="success"` - NVMe target connected, ready for block mount
- `status="failure"` - Failed to connect (e.g., discovery service unreachable, NQN mismatch)

**When to investigate:**
- If `status="failure"` is increasing
- If connect failures correlate with storage system issues

---

### `csi_node_nvme_connect_duration_seconds`

**Type:** Histogram  
**Description:** Duration of NVMe-oF connect operations in seconds.  
**When you see it:** Recorded for every NVMe connect operation.

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `node_name` | Kubernetes node | `worker-node-1`, `k8s-worker-02` |

**Buckets:** Same as mount duration (1s, 5s, 20s, +Inf)

**Typical values:**
- **NVMe connect:** <1 second (fast), 1-5 seconds (normal), >5 seconds (slow)

**When to investigate:**
- If connect duration > 10 seconds consistently

---

## NVMe Controller Metrics

These metrics provide real-time information about NVMe controllers connected on the node.

**Availability:**
- **Automatically enabled** for **vastblock** (block driver) node pods
- **Automatically disabled** for **vastcsi** (NFS driver) node pods, since NFS driver doesn't use NVMe
- The driver automatically determines whether to collect these metrics based on the driver type at startup
- **Only collected on node services** (DaemonSet pods), not available on controller pods
- Updated every time `/metrics` is scraped

For the NFS driver, the `csi_node_nvme_controller_info` metric will not appear in the `/metrics` output.

### `csi_node_nvme_controller_info`

**Type:** Gauge
**Description:** NVMe controller information metric for **VAST controllers only**. Each connected VAST NVMe controller (model="VASTData") generates one time series with value `1`. Physical NVMe devices and other vendors are filtered out. When a controller is removed, its time series disappears.

**When you see it:** On block driver node pods (port 9092) when VAST NVMe volumes are connected.

**Labels:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `controller` | NVMe controller name | `nvme0`, `nvme1`, `nvme2` |
| `subsysnqn` | Subsystem NQN | `nqn.2024-08.com.vastdata:default:myblock` |
| `hostnqn` | Host NQN used for connection | `nqn.2014-08.com.vastcsiblock:node1` |
| `transport` | Transport type | `tcp`, `rdma` |
| `address` | Target address (traddr) only | `172.21.112.4`, `10.95.40.74` |
| `state` | Controller state from kernel | `live`, `connecting`, `resetting`, `deleting`, `dead` |
| `model` | Device model name | `VastData` |
| `serial` | Device serial number | `VastData` |

**Typical values:**
- **Value:** Always `1` when controller is present
- **State:** `live` is healthy, `connecting`/`resetting` during transitions, `dead` indicates failure
- **Transport:** Typically `tcp` (VAST block uses NVMe-TCP)

**Example Metrics:**

```promql
csi_node_nvme_controller_info{
  controller="nvme0",
  subsysnqn="nqn.2024-08.com.vastdata:default:myblock",
  hostnqn="nqn.2014-08.com.vastcsiblock:node1",
  transport="tcp",
  address="172.21.112.4",
  state="live",
  model="VastData",
  serial="VastData"
} 1

csi_node_nvme_controller_info{
  controller="nvme1",
  subsysnqn="nqn.2024-08.com.vastdata:default:myblock",
  hostnqn="nqn.2014-08.com.vastcsiblock:node1",
  transport="tcp",
  address="172.21.112.5",
  state="live",
  model="VastData",
  serial="VastData"
} 1
```

**When to investigate:**
- If `state != "live"` for extended periods (indicates controller issues)
- If expected controllers are missing (multipath issues)
- If controller count changes unexpectedly

**Useful Queries:**

```promql
# Count total NVMe controllers per node
count by (node_name) (csi_node_nvme_controller_info)

# Find controllers not in live state
csi_node_nvme_controller_info{state!="live"}

# Count controllers per subsystem
count by (subsysnqn) (csi_node_nvme_controller_info)

# List all unique controller states
count by (state) (csi_node_nvme_controller_info)
```

---

## NFS Transport (xprt) Metrics

These metrics are collected from the Linux kernel's NFS transport subsystem (`/sys/kernel/sunrpc/xprt-switches`).

**Availability:**
- **Automatically enabled** for **vastcsi** (NFS driver) node pods
- **Automatically disabled** for **vastblock** (block driver) node pods, since block drivers use NVMe-oF instead of NFS
- The driver automatically determines whether to collect these metrics based on the driver type at startup
- **Only collected on node services** (DaemonSet pods), not available on controller pods

For the block driver, none of the `csi_node_nfs_xprt_*` metrics will appear in the `/metrics` output.

### Aggregate Metrics (Always Visible When Enabled)

These metrics are **always present** in `/metrics` output when NFS xprt collection is enabled, even when value is 0.

#### `csi_node_nfs_xprt_total`

**Type:** Gauge  
**Description:** Total number of active NFS transports (after filtering).  
**When you see it:** Always (even when 0).

**Labels:** None

**Example Values:**

```promql
# 2 active NFS transports
csi_node_nfs_xprt_total 2.0

# No active transports (all volumes unmounted)
csi_node_nfs_xprt_total 0.0
```

**What it means:**
- Number of NFS connections currently active on this node
- Excludes CLOSED, local, and unknown transports (see filtering logic)

**Typical values:**
- 0 = No NFS volumes mounted
- 1-10 = Normal (1-10 NFS PVCs mounted)
- 50+ = High (many NFS volumes on single node)

**When to investigate:**
- If total is much higher than number of mounted NFS PVCs (may indicate leaks)
- If total never decreases after unmount (transport cleanup issue)

---

#### `csi_node_nfs_xprt_connected`

**Type:** Gauge  
**Description:** Number of transports in CONNECTED state (both CONNECTED and BOUND flags set).  
**When you see it:** Always (even when 0).

**Labels:** None

**Example Values:**

```promql
# All transports are connected
csi_node_nfs_xprt_total 2.0
csi_node_nfs_xprt_connected 2.0

# 1 out of 2 transports is not connected
csi_node_nfs_xprt_total 2.0
csi_node_nfs_xprt_connected 1.0
```

**What it means:**
- How many transports are fully connected and ready for I/O
- Should typically equal `xprt_total` (all transports connected)

**When to investigate:**
- If `connected` < `total` (some transports are not connected)
- If `connected` drops to 0 while volumes are still mounted (network issue)

---

#### `csi_node_nfs_xprt_pending_requests_total`

**Type:** Gauge  
**Description:** Total pending RPC requests across all transports.  
**When you see it:** Always (even when 0).

**Labels:** None

**Example Values:**

```promql
# No pending requests (idle)
csi_node_nfs_xprt_pending_requests_total 0.0

# 5 requests pending
csi_node_nfs_xprt_pending_requests_total 5.0

# High pending requests (congestion)
csi_node_nfs_xprt_pending_requests_total 150.0
```

**What it means:**
- Number of NFS operations waiting for response from server
- Low values = normal, high values = congestion or slow storage

**Typical values:**
- 0-10 = Normal (idle or light load)
- 10-50 = Moderate load
- 100+ = High load or congestion

**When to investigate:**
- If pending requests stay high (>100) for extended periods
- If pending increases but no I/O happening (hung transport)

---

#### `csi_node_nfs_xprt_backlog_total`

**Type:** Gauge  
**Description:** Total backlog queue depth across all transports.  
**When you see it:** Always (even when 0).

**Labels:** None

**Example Values:**

```promql
# No backlog (good)
csi_node_nfs_xprt_backlog_total 0.0

# Some backlog (congestion)
csi_node_nfs_xprt_backlog_total 25.0
```

**What it means:**
- Number of requests queued waiting to be sent (not yet sent to server)
- Non-zero values indicate congestion or flow control

**Typical values:**
- 0 = Normal (no congestion)
- 1-20 = Mild congestion
- 50+ = Severe congestion

**When to investigate:**
- If backlog is consistently > 0 (flow control active)
- If backlog grows over time (transport not draining)

---

#### `csi_node_nfs_xprt_unhealthy`

**Type:** Gauge  
**Description:** Number of transports with potential issues.  
**When you see it:** Always (even when 0).

**Labels:** None

**Unhealthy conditions:**
- Transport is not CONNECTED
- Transport has OFFLINE, CLOSING, or CLOSE_WAIT flags
- Transport is CONGESTED
- Pending requests > 100
- Backlog depth > 50

**Example Values:**

```promql
# All transports healthy
csi_node_nfs_xprt_unhealthy 0.0

# 1 transport has issues
csi_node_nfs_xprt_unhealthy 1.0
```

**When to investigate:**
- If `unhealthy` > 0 (at least one transport has issues)
- Check per-destination metrics to identify which VIP is affected

---

### Per-Destination Metrics (Conditional)

These metrics only appear when at least one transport exists for a destination. When all transports to a destination disappear, the metric is **completely removed** (not set to 0).

**Important:** In these metrics, `destination` = **VIP (Virtual IP)** of the VAST cluster. Each VIP gets its own set of metrics to track the health and performance of connections to that specific storage endpoint.

**Common label for all per-destination metrics:**

| Label | Description | Example Values |
|-------|-------------|----------------|
| `destination` | **VIP (Virtual IP)** - VAST cluster IP address | `192.168.1.10`, `10.0.0.5`, `2001:db8::1` |

**Note:** The `destination` label represents the **VIP (Virtual IP)** of the VAST cluster. This is the IP address that NFS clients connect to for storage access. Each unique VIP will have its own set of per-destination metrics.

---

#### `csi_node_nfs_xprt_connected_state`

**Type:** Gauge  
**Description:** Per-destination connected state (1 = connected, 0 = not connected).  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# Both VIPs are connected
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 1.0

# One VIP is not connected (issue with 192.168.1.20)
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 0.0
```

**What it means:**
- `1.0` = Transport is connected (CONNECTED + BOUND flags set)
- `0.0` = Transport exists but is not connected (network issue, mounting, etc.)

**When to investigate:**
- If value is `0.0` for any destination (transport not connected)
- If value flaps between 0 and 1 (unstable connection)

---

#### `csi_node_nfs_xprt_congested_state`

**Type:** Gauge  
**Description:** Per-destination congestion state (1 = congested, 0 = not congested).  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# No congestion
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 0.0

# 192.168.1.10 is congested
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 0.0
```

**What it means:**
- `1.0` = Transport has CONGESTED or CWND_WAIT flags (flow control active)
- `0.0` = Transport is not congested

**When to investigate:**
- If value is `1.0` for extended periods (sustained congestion)
- If congestion affects specific VIPs only (network or storage issue)

---

#### `csi_node_nfs_xprt_locked_state`

**Type:** Gauge  
**Description:** Per-destination locked state (1 = locked, 0 = not locked).  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# No locks
csi_node_nfs_xprt_locked_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.20"} 0.0
```

**What it means:**
- `1.0` = Transport has LOCKED flag (transport is locked for exclusive operation)
- `0.0` = Transport is not locked

**Typical values:**
- Usually `0.0` (locked state is transient during reconnect)

**When to investigate:**
- If value stays `1.0` for extended periods (transport stuck in locked state)

---

#### `csi_node_nfs_xprt_pending_requests`

**Type:** Gauge  
**Description:** Number of pending RPC requests for this destination.  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# Light load
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 3.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 1.0

# High load on 192.168.1.10
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 120.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 5.0
```

**What it means:**
- Number of NFS operations waiting for response from this specific VIP

**Typical values:**
- 0-10 = Normal
- 10-50 = Moderate load
- 100+ = High load or congestion

**When to investigate:**
- If pending > 100 for any destination (congestion or slow storage)
- If one VIP has much higher pending than others (imbalance)

---

#### `csi_node_nfs_xprt_backlog_depth`

**Type:** Gauge  
**Description:** Backlog queue depth for this destination.  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# No backlog (good)
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.20"} 0.0

# Backlog on 192.168.1.10
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 30.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.20"} 0.0
```

**What it means:**
- Number of requests queued waiting to be sent to this VIP

**Typical values:**
- 0 = Normal (no flow control)
- 1-20 = Mild congestion
- 50+ = Severe congestion

**When to investigate:**
- If backlog > 0 consistently (flow control active)
- If backlog affects specific VIPs only (network or storage issue)

---

#### `csi_node_nfs_xprt_mounts`

**Type:** Gauge  
**Description:** Number of active NFS mounts using this transport destination.  
**When you see it:** Only when at least one transport exists to this destination.

**Example Metrics:**

```promql
# Single mount to each VIP
csi_node_nfs_xprt_mounts{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_mounts{destination="192.168.1.20"} 1.0

# Multiple mounts to 192.168.1.10 (good transport multiplexing)
csi_node_nfs_xprt_mounts{destination="192.168.1.10"} 5.0
csi_node_nfs_xprt_mounts{destination="192.168.1.20"} 2.0

# No mounts (transport exists but not actively used)
csi_node_nfs_xprt_mounts{destination="192.168.1.10"} 0.0
```

**What it means:**
- Number of NFS volumes currently mounted from this VIP
- Shows transport utilization (one transport can serve multiple mounts)
- Value of 0 indicates transport exists but no active mounts (e.g., during unmount)

**Typical values:**
- 0 = No active mounts (transport idle or being cleaned up)
- 1-10 = Normal (typical pod count per node)
- 10+ = High utilization (many pods with NFS volumes)

**When to investigate:**
- If mount count is 0 but transport still exists (cleanup delay)
- If mount count is unexpectedly high (pod sprawl, resource exhaustion)

**Use cases:**
- Capacity planning: understand how many mounts per transport
- Transport efficiency: higher values = better multiplexing
- Debugging: correlate mount count with transport health

---

## Understanding Labels

### How Labels Work

Labels allow you to filter metrics by specific dimensions. You can query specific combinations:

```promql
# All mount operations in 'prod' namespace
csi_node_mount_operations_total{pvc_namespace="prod"}

# Failed mounts on worker-node-1
csi_node_mount_operations_total{node_name="worker-node-1",status="failure"}

# NFS mount failures in any namespace
csi_node_mount_operations_total{operation_type="nfs",status="failure"}
```

### Common Label Values

#### `operation_type`

| Value | Description | When you see it |
|-------|-------------|-----------------|
| `nfs` | NFS mount/unmount | NFS PVCs (vastcsi driver) |
| `block_mount` | Block device mount | Block PVCs after NVMe connect (vastblock driver) |
| `bind_mount` | Bind mount (internal) | Subpath volumes or read-only mounts |

#### `status`

| Value | Description | When you see it |
|-------|-------------|-----------------|
| `success` | Operation completed successfully | Normal operations |
| `failure` | Operation failed (non-timeout error) | Network issues, permission errors, invalid config |
| `timeout` | Operation timed out | Slow network, storage unresponsive, hung operations |

#### `node_name`

Kubernetes node name where the CSI operation happened. Examples:
- `worker-node-1`, `worker-node-2`, `worker-node-3`
- `ip-10-0-1-45.ec2.internal` (AWS)
- `gke-cluster-pool-1-a4f8c2d1-abc123` (GKE)

#### `pvc_namespace`

Kubernetes namespace containing the PVC being mounted/unmounted. Examples:
- `default` - Default namespace
- `prod`, `staging`, `dev` - Environment namespaces
- `team-alpha`, `team-beta` - Team namespaces
- `kube-system` - System namespace

#### `destination`

**VIP (Virtual IP) / server IP address** for NFS transports (port stripped).

**Note:** In VAST CSI context, `destination` refers to the **VIP (Virtual IP)** of the VAST cluster that the NFS mount is connected to. This is the IP address specified in the StorageClass or PVC configuration.

Examples:
- `192.168.1.10` - IPv4 VIP
- `10.0.0.5` - IPv4 VIP
- `2001:db8::1` - IPv6 VIP

---

## Common Scenarios and Expected Metrics

### Scenario 1: Mount a New PVC

**Action:** `kubectl apply -f pvc.yaml` → Pod starts using PVC

**Expected Metrics:**

```promql
# Mount counter increases by 1
csi_node_mount_operations_total{operation_type="nfs",status="success",node_name="worker-1",pvc_namespace="default"} 1

# Mount duration recorded (e.g., 1.2 seconds)
csi_node_mount_duration_seconds_count{operation_type="nfs",node_name="worker-1",pvc_namespace="default"} 1
csi_node_mount_duration_seconds_sum{operation_type="nfs",node_name="worker-1",pvc_namespace="default"} 1.2

# NFS transport appears
csi_node_nfs_xprt_total 1.0
csi_node_nfs_xprt_connected 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 0.0
```

---

### Scenario 2: Unmount a PVC

**Action:** `kubectl delete pod <pod>` → PVC is unmounted

**Expected Metrics:**

```promql
# Unmount counter increases by 1
csi_node_umount_operations_total{operation_type="nfs",status="success",node_name="worker-1",pvc_namespace="default"} 1

# Unmount duration recorded (e.g., 0.5 seconds)
csi_node_umount_duration_seconds_count{operation_type="nfs",node_name="worker-1",pvc_namespace="default"} 1
csi_node_umount_duration_seconds_sum{operation_type="nfs",node_name="worker-1",pvc_namespace="default"} 0.5

# NFS transport disappears (after 30s metric update)
csi_node_nfs_xprt_total 0.0
csi_node_nfs_xprt_connected 0.0
# Per-destination metrics are COMPLETELY REMOVED (not set to 0)
# csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} - GONE
```

---

### Scenario 3: Mount Timeout

**Action:** Storage is unreachable, mount hangs

**Expected Metrics:**

```promql
# Mount fails with timeout status
csi_node_mount_operations_total{operation_type="nfs",status="timeout",node_name="worker-1",pvc_namespace="prod"} 1

# Duration recorded as ~30 seconds (timeout threshold)
csi_node_mount_duration_seconds_count{operation_type="nfs",node_name="worker-1",pvc_namespace="prod"} 1
csi_node_mount_duration_seconds_sum{operation_type="nfs",node_name="worker-1",pvc_namespace="prod"} 30.1

# No NFS transport appears (mount failed before establishing transport)
csi_node_nfs_xprt_total 0.0
```

---

### Scenario 4: Multiple PVCs on Same Node

**Action:** 3 PVCs mounted on worker-1 (2 to VIP 192.168.1.10, 1 to VIP 192.168.1.20)

**Expected Metrics:**

```promql
# 3 total transports (1 per PVC)
csi_node_nfs_xprt_total 3.0
csi_node_nfs_xprt_connected 3.0

# Per-destination metrics show aggregated stats
# Note: Multiple PVCs to same VIP may share same transport or create multiple transports
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 1.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 5.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 2.0
```

---

### Scenario 5: Network Issue (Transport Disconnected)

**Action:** Network link to storage goes down, transport loses connection

**Expected Metrics:**

```promql
# Transport still exists but not connected
csi_node_nfs_xprt_total 1.0
csi_node_nfs_xprt_connected 0.0

# Per-destination shows not connected
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 0.0

# Pending requests may accumulate
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 80.0

# Unhealthy counter increases
csi_node_nfs_xprt_unhealthy 1.0
```

---

### Scenario 6: Storage Congestion

**Action:** Storage system is overloaded, responses are slow

**Expected Metrics:**

```promql
# Transports are connected but congested
csi_node_nfs_xprt_total 2.0
csi_node_nfs_xprt_connected 2.0

# Congestion flags set
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 1.0

# High pending requests
csi_node_nfs_xprt_pending_requests_total 150.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 80.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 70.0

# Unhealthy due to congestion
csi_node_nfs_xprt_unhealthy 2.0
```

---

## QA Testing Checklists

### Basic Functionality Testing

- [ ] Mount a PVC → `csi_node_mount_operations_total{status="success"}` increases by 1
- [ ] Mount duration < 5 seconds → Check `csi_node_mount_duration_seconds`
- [ ] NFS transport appears → `csi_node_nfs_xprt_total` increases by 1
- [ ] Transport is connected → `csi_node_nfs_xprt_connected_state{destination="..."}` = 1
- [ ] Unmount PVC → `csi_node_umount_operations_total{status="success"}` increases by 1
- [ ] Transport disappears → Per-destination metrics are completely removed (not visible in `/metrics`)

### Error Handling Testing

- [ ] Mount to unreachable storage → `status="timeout"` or `status="failure"`
- [ ] Mount with invalid export → `status="failure"`
- [ ] Unmount already-unmounted path → No failure counter increase (idempotency)

### Label Verification Testing

- [ ] Mount in namespace "prod" → `pvc_namespace="prod"` label appears
- [ ] Mount on worker-node-2 → `node_name="worker-node-2"` label appears
- [ ] NFS mount → `operation_type="nfs"` label
- [ ] Block mount → `operation_type="block_mount"` label

### Transport Filtering Testing

- [ ] Local transport (127.0.0.1) → Should NOT appear in metrics (filtered out)
- [ ] CLOSED transport → Should NOT appear in metrics (filtered out)
- [ ] Unknown destination → Should NOT appear in metrics (filtered out)
- [ ] Real VIP (e.g., 192.168.1.10) → Should appear in metrics

### Multi-VIP Testing

- [ ] Mount to VIP 192.168.1.10 → `destination="192.168.1.10"` metrics appear
- [ ] Mount to VIP 192.168.1.20 → `destination="192.168.1.20"` metrics appear (separate)
- [ ] Unmount from 192.168.1.10 → Only that destination's metrics disappear

---

## Troubleshooting with Metrics

### Problem: Pods stuck in ContainerCreating

**Check:**
```promql
# Look for mount failures
csi_node_mount_operations_total{status="failure"}

# Look for mount timeouts
csi_node_mount_operations_total{status="timeout"}

# Check mount duration
rate(csi_node_mount_duration_seconds_sum[5m]) / rate(csi_node_mount_duration_seconds_count[5m])
```

**Expected:** If pods are stuck, you should see increasing failure or timeout counters.

---

### Problem: Slow mount performance

**Check:**
```promql
# Average mount duration by namespace
rate(csi_node_mount_duration_seconds_sum[5m]) / rate(csi_node_mount_duration_seconds_count[5m])
by (pvc_namespace)

# 95th percentile mount duration
histogram_quantile(0.95, rate(csi_node_mount_duration_seconds_bucket[5m]))
```

**Expected:** Normal mount duration < 5 seconds. If > 10 seconds, investigate network/storage.

---

### Problem: Transport not connecting

**Check:**
```promql
# Disconnected transports
csi_node_nfs_xprt_total - csi_node_nfs_xprt_connected

# Per-destination connection state
csi_node_nfs_xprt_connected_state
```

**Expected:** `connected` should equal `total`. If not, check network connectivity to that VIP.

---

### Problem: High pending requests

**Check:**
```promql
# Aggregate pending requests
csi_node_nfs_xprt_pending_requests_total

# Per-destination pending requests
csi_node_nfs_xprt_pending_requests
```

**Expected:** Pending requests < 50 normally. If > 100, check storage performance and congestion flags.

---

## Useful PromQL Queries for QA

```promql
# Mount success rate (last 5 minutes)
rate(csi_node_mount_operations_total{status="success"}[5m])
/ rate(csi_node_mount_operations_total[5m])

# Average mount duration by namespace
rate(csi_node_mount_duration_seconds_sum[5m])
/ rate(csi_node_mount_duration_seconds_count[5m])
by (pvc_namespace)

# Failed mounts per node
sum(rate(csi_node_mount_operations_total{status="failure"}[5m])) by (node_name)

# Total active NFS transports across all nodes
sum(csi_node_nfs_xprt_total)

# Unhealthy transports
sum(csi_node_nfs_xprt_unhealthy)

# Which destinations have congestion
csi_node_nfs_xprt_congested_state == 1

# Total pending requests across all nodes
sum(csi_node_nfs_xprt_pending_requests_total)
```

---

## References

- **User Setup Guide:** `docs/METRICS_GUIDE.md` - How to enable and configure metrics
- **Developer Guide:** `METRICS_DEVELOPER_GUIDE.md` - Internal implementation details
- **QA Fixes:** `XPRT_QA_FIXES_V2.6.md` - Filtering logic and QA-driven improvements
