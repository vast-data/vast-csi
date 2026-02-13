# Real Metrics Examples

This document shows **actual Prometheus metrics output** from the VAST CSI driver in different scenarios. Use these examples to verify your metrics implementation is working correctly.

**Port Reference:**
- vastcsi (NFS): Node=9090, Controller=9091
- vastblock (Block): Node=9092, Controller=9093

**Important Notes:**
- Examples below use port 9090, which applies to vastcsi (NFS). For vastblock, substitute 9092 for node metrics.
- **NFS transport (xprt) metrics** (`csi_node_nfs_xprt_*`) are **automatically disabled for vastblock** and enabled for vastcsi. The driver automatically determines this based on whether it's using NFS or NVMe-oF transport.

---

## How to View Metrics

```bash
# vastcsi (NFS) - Port-forward to a CSI node pod
kubectl port-forward -n vast-csi <vastcsi-node-pod-name> 9090:9090

# vastblock (Block) - Port-forward to a CSI node pod
kubectl port-forward -n vast-csi <vastblock-node-pod-name> 9092:9092

# In another terminal, fetch metrics
curl -s http://localhost:9090/metrics | grep csi_node  # for vastcsi
curl -s http://localhost:9092/metrics | grep csi_node  # for vastblock
```

---

## Example 1: Fresh Node (No Volumes Mounted)

**Scenario:** CSI node pod just started, no PVCs mounted yet.

**Expected Output:**

```promql
# HELP csi_node_mount_operations_total Total number of mount operations
# TYPE csi_node_mount_operations_total counter
# (no data yet - counters start at 0, not shown until first increment)

# HELP csi_node_mount_duration_seconds Duration of mount operations in seconds
# TYPE csi_node_mount_duration_seconds histogram
# (no data yet)

# HELP csi_node_umount_operations_total Total number of unmount operations
# TYPE csi_node_umount_operations_total counter
# (no data yet)

# HELP csi_node_umount_duration_seconds Duration of unmount operations in seconds
# TYPE csi_node_umount_duration_seconds histogram
# (no data yet)

# HELP csi_node_nfs_xprt_total Total number of NFS transports
# TYPE csi_node_nfs_xprt_total gauge
csi_node_nfs_xprt_total 0.0

# HELP csi_node_nfs_xprt_connected Number of NFS transports in CONNECTED state
# TYPE csi_node_nfs_xprt_connected gauge
csi_node_nfs_xprt_connected 0.0

# HELP csi_node_nfs_xprt_pending_requests_total Total pending RPC requests across all transports
# TYPE csi_node_nfs_xprt_pending_requests_total gauge
csi_node_nfs_xprt_pending_requests_total 0.0

# HELP csi_node_nfs_xprt_backlog_total Total backlog queue depth across all transports
# TYPE csi_node_nfs_xprt_backlog_total gauge
csi_node_nfs_xprt_backlog_total 0.0

# HELP csi_node_nfs_xprt_unhealthy Number of transports with potential issues
# TYPE csi_node_nfs_xprt_unhealthy gauge
csi_node_nfs_xprt_unhealthy 0.0

# No per-destination metrics (no transports exist)
```

**Key Points:**
- Aggregate xprt metrics show `0.0` (always visible)
- No per-destination metrics (none exist yet)
- No mount/unmount counters (haven't happened yet)

---

## Example 2: After Mounting 1 NFS PVC

**Scenario:** Mounted 1 NFS PVC in namespace `default` to VIP `192.168.1.10`.

**Note:** VIP (Virtual IP) is the VAST cluster IP address that appears in the `destination` label of per-destination metrics.

**Command:**
```bash
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
  namespace: default
spec:
  accessModes: [ReadWriteMany]
  resources:
    requests:
      storage: 10Gi
  storageClassName: vast-nfs
EOF

kubectl run test-pod --image=nginx --restart=Never \
  -n default --overrides='{"spec":{"volumes":[{"name":"vol","persistentVolumeClaim":{"claimName":"test-pvc"}}],"containers":[{"name":"nginx","image":"nginx","volumeMounts":[{"name":"vol","mountPath":"/data"}]}]}}'
```

**Expected Output (after ~30 seconds):**

```promql
# HELP csi_node_mount_operations_total Total number of mount operations
# TYPE csi_node_mount_operations_total counter
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",status="success"} 1.0

# HELP csi_node_mount_duration_seconds Duration of mount operations in seconds
# TYPE csi_node_mount_duration_seconds histogram
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="1.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="5.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="20.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="+Inf"} 1.0
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default"} 0.823
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default"} 1.0

# HELP csi_node_nfs_xprt_total Total number of NFS transports
# TYPE csi_node_nfs_xprt_total gauge
csi_node_nfs_xprt_total 1.0

# HELP csi_node_nfs_xprt_connected Number of NFS transports in CONNECTED state
# TYPE csi_node_nfs_xprt_connected gauge
csi_node_nfs_xprt_connected 1.0

# HELP csi_node_nfs_xprt_pending_requests_total Total pending RPC requests across all transports
# TYPE csi_node_nfs_xprt_pending_requests_total gauge
csi_node_nfs_xprt_pending_requests_total 0.0

# HELP csi_node_nfs_xprt_backlog_total Total backlog queue depth across all transports
# TYPE csi_node_nfs_xprt_backlog_total gauge
csi_node_nfs_xprt_backlog_total 0.0

# HELP csi_node_nfs_xprt_unhealthy Number of transports with potential issues
# TYPE csi_node_nfs_xprt_unhealthy gauge
csi_node_nfs_xprt_unhealthy 0.0

# HELP csi_node_nfs_xprt_connected_state Transport is connected (CONNECTED and BOUND flags set)
# TYPE csi_node_nfs_xprt_connected_state gauge
# Note: destination = VIP (Virtual IP) of VAST cluster
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0

# HELP csi_node_nfs_xprt_congested_state Transport is congested (CONGESTED or CWND_WAIT flags set)
# TYPE csi_node_nfs_xprt_congested_state gauge
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 0.0

# HELP csi_node_nfs_xprt_locked_state Transport is locked (LOCKED flag set)
# TYPE csi_node_nfs_xprt_locked_state gauge
csi_node_nfs_xprt_locked_state{destination="192.168.1.10"} 0.0

# HELP csi_node_nfs_xprt_pending_requests Number of pending RPC requests for this transport
# TYPE csi_node_nfs_xprt_pending_requests gauge
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 0.0

# HELP csi_node_nfs_xprt_backlog_depth Backlog queue depth for this transport
# TYPE csi_node_nfs_xprt_backlog_depth gauge
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 0.0
```

**Key Points:**
- Mount counter increased by 1 with `status="success"`
- Mount took 0.823 seconds (shown in `le="1.0"` bucket)
- 1 NFS transport appeared for `destination="192.168.1.10"`
- Transport is connected (`xprt_connected_state=1.0`)
- No congestion or pending requests (healthy state)

---

## Example 3: After Mounting 3 PVCs to Different VIPs

**Scenario:** 
- PVC 1 in namespace `prod` → VIP `192.168.1.10`
- PVC 2 in namespace `prod` → VIP `192.168.1.20`
- PVC 3 in namespace `dev` → VIP `192.168.1.10` (same VIP as PVC 1)

**Note:** VIP = Virtual IP of VAST cluster (shown as `destination` label in metrics)

**Expected Output:**

```promql
# Mount counters by namespace
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod",status="success"} 2.0
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev",status="success"} 1.0

# Mount duration histogram (prod namespace)
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod"} 1.654
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod"} 2.0

# Mount duration histogram (dev namespace)
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev"} 0.912
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev"} 1.0

# Aggregate xprt metrics
csi_node_nfs_xprt_total 3.0
csi_node_nfs_xprt_connected 3.0
csi_node_nfs_xprt_pending_requests_total 0.0
csi_node_nfs_xprt_backlog_total 0.0
csi_node_nfs_xprt_unhealthy 0.0

# Per-destination metrics (2 VIPs, multiple transports possible)
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 1.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.20"} 0.0
```

**Key Points:**
- 3 mounts total: 2 in `prod`, 1 in `dev`
- 3 transports total (kernel may create 1 per mount or share transports)
- 2 unique destinations: `192.168.1.10` and `192.168.1.20`
- Average mount time in prod: 1.654/2 = 0.827 seconds
- Average mount time in dev: 0.912/1 = 0.912 seconds

---

## Example 4: After Unmounting 1 PVC

**Scenario:** Delete the pod using PVC in `dev` namespace, wait 30s for metric update.

**Command:**
```bash
kubectl delete pod test-pod -n dev
# Wait 30 seconds for xprt metrics to update
sleep 30
```

**Expected Output:**

```promql
# Mount counters (unchanged - counters never decrease)
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod",status="success"} 2.0
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev",status="success"} 1.0

# Unmount counter appears (new!)
csi_node_umount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev",status="success"} 1.0

# Unmount duration
csi_node_umount_duration_seconds_sum{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev"} 0.341
csi_node_umount_duration_seconds_count{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev"} 1.0

# Aggregate xprt metrics (1 transport removed)
csi_node_nfs_xprt_total 2.0
csi_node_nfs_xprt_connected 2.0
csi_node_nfs_xprt_pending_requests_total 0.0
csi_node_nfs_xprt_backlog_total 0.0
csi_node_nfs_xprt_unhealthy 0.0

# Per-destination metrics (both VIPs still have transports from prod namespace)
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 1.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 0.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.20"} 0.0
```

**Key Points:**
- Unmount counter appeared with 1 successful unmount
- Unmount took 0.341 seconds (faster than mount)
- Transport count decreased from 3 to 2
- Both destinations still have transports (prod PVCs still mounted)

---

## Example 5: After Unmounting All PVCs

**Scenario:** Delete all pods/PVCs, wait for cleanup.

**Expected Output:**

```promql
# Mount counters (unchanged - counters are cumulative)
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod",status="success"} 2.0
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev",status="success"} 1.0

# Unmount counters (all 3 unmounts recorded)
csi_node_umount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="prod",status="success"} 2.0
csi_node_umount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="dev",status="success"} 1.0

# Aggregate xprt metrics (all transports gone)
csi_node_nfs_xprt_total 0.0
csi_node_nfs_xprt_connected 0.0
csi_node_nfs_xprt_pending_requests_total 0.0
csi_node_nfs_xprt_backlog_total 0.0
csi_node_nfs_xprt_unhealthy 0.0

# Per-destination metrics COMPLETELY REMOVED (not visible at all)
# No csi_node_nfs_xprt_connected_state metrics
# No csi_node_nfs_xprt_congested_state metrics
# No csi_node_nfs_xprt_locked_state metrics
# No csi_node_nfs_xprt_pending_requests metrics
# No csi_node_nfs_xprt_backlog_depth metrics
```

**Key Points:**
- Mount/unmount counters show full history (3 mounts, 3 unmounts)
- Aggregate xprt metrics all at 0 (always visible)
- **Per-destination metrics completely removed** (not shown in output)
- This is expected behavior (QA should verify no stale metrics remain)

---

## Example 6: Mount Failure (Storage Unreachable)

**Scenario:** Try to mount but storage VIP is unreachable (e.g., network issue).

**Expected Output:**

```promql
# Failed mount counter
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",status="failure"} 1.0

# OR timeout counter (if it takes > 30 seconds)
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",status="timeout"} 1.0

# Duration recorded even for failures
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="20.0"} 0.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default",le="+Inf"} 1.0
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default"} 30.123
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="nfs",pvc_namespace="default"} 1.0

# No transport created (mount failed before establishing connection)
csi_node_nfs_xprt_total 0.0
csi_node_nfs_xprt_connected 0.0
```

**Key Points:**
- `status="failure"` or `status="timeout"` counter increased
- Duration shows ~30 seconds (timeout threshold)
- No transport created (connection never established)

---

## Example 7: Storage Congestion

**Scenario:** Storage system is overloaded, transports show congestion.

**Expected Output:**

```promql
# Transports exist and connected
csi_node_nfs_xprt_total 2.0
csi_node_nfs_xprt_connected 2.0

# High pending requests (congestion indicator)
csi_node_nfs_xprt_pending_requests_total 180.0

# Some backlog accumulating
csi_node_nfs_xprt_backlog_total 35.0

# Unhealthy count increased (due to high pending requests)
csi_node_nfs_xprt_unhealthy 2.0

# Per-destination shows congestion flags
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_connected_state{destination="192.168.1.20"} 1.0

# Congestion flags SET
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 1.0
csi_node_nfs_xprt_congested_state{destination="192.168.1.20"} 1.0

csi_node_nfs_xprt_locked_state{destination="192.168.1.10"} 0.0
csi_node_nfs_xprt_locked_state{destination="192.168.1.20"} 0.0

# High pending requests per VIP
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 95.0
csi_node_nfs_xprt_pending_requests{destination="192.168.1.20"} 85.0

# Backlog accumulating
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.10"} 18.0
csi_node_nfs_xprt_backlog_depth{destination="192.168.1.20"} 17.0
```

**Key Points:**
- `xprt_congested_state=1.0` indicates flow control active
- High pending requests (>100 total across transports)
- `xprt_unhealthy=2.0` (all transports unhealthy due to congestion)
- This indicates storage performance issue or network bottleneck

---

## Example 8: Network Failure (Transport Disconnected)

**Scenario:** Network link to storage fails, transport loses connection.

**Expected Output:**

```promql
# Transport exists but not connected
csi_node_nfs_xprt_total 1.0
csi_node_nfs_xprt_connected 0.0

# Pending requests may accumulate while reconnecting
csi_node_nfs_xprt_pending_requests_total 42.0

# Unhealthy (not connected)
csi_node_nfs_xprt_unhealthy 1.0

# Per-destination shows NOT connected
csi_node_nfs_xprt_connected_state{destination="192.168.1.10"} 0.0

# May or may not be congested
csi_node_nfs_xprt_congested_state{destination="192.168.1.10"} 0.0

# Pending requests accumulating
csi_node_nfs_xprt_pending_requests{destination="192.168.1.10"} 42.0
```

**Key Points:**
- `xprt_total > 0` but `xprt_connected = 0` (transport exists but disconnected)
- `xprt_connected_state=0.0` indicates not connected
- Pending requests accumulate while trying to reconnect
- Pods using this volume will experience I/O hangs

---

## Example 9: Block Driver (NVMe-oF) - Complete Lifecycle

**Scenario:** Full lifecycle of a block PVC using NVMe-oF: mount, use, and unmount.

**Steps:**
1. Pod scheduled → NVMe connect to VAST subsystem
2. Block device mounted to pod
3. Pod deleted → Block device unmounted
4. NVMe disconnect

**Expected Output:**

```promql
# ============================================================
# STEP 1: NVMe Connect Operation
# ============================================================

# NVMe connect counter (successful)
csi_node_nvme_connect_operations_total{node_name="worker-node-1",status="success"} 1.0

# NVMe connect duration histogram (took 2.3 seconds - normal for initial connect)
# TYPE csi_node_nvme_connect_duration_seconds histogram
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="1.0"} 0.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="5.0"} 1.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="20.0"} 1.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="+Inf"} 1.0
csi_node_nvme_connect_duration_seconds_sum{node_name="worker-node-1"} 2.341
csi_node_nvme_connect_duration_seconds_count{node_name="worker-node-1"} 1.0

# ============================================================
# STEP 2: Block Device Mount
# ============================================================

# Block mount counter (successful)
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",status="success"} 1.0

# Block mount duration histogram (took 0.15 seconds - very fast, just bind mount)
# TYPE csi_node_mount_duration_seconds histogram
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="1.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="5.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="20.0"} 1.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="+Inf"} 1.0
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 0.152
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 1.0

# ============================================================
# STEP 3: Block Device Unmount
# ============================================================

# Block unmount counter (successful)
csi_node_umount_operations_total{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",status="success"} 1.0

# Block unmount duration histogram (took 0.08 seconds - very fast)
# TYPE csi_node_umount_duration_seconds histogram
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="1.0"} 1.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="5.0"} 1.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="20.0"} 1.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="+Inf"} 1.0
csi_node_umount_duration_seconds_sum{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 0.083
csi_node_umount_duration_seconds_count{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 1.0

# ============================================================
# WHAT'S MISSING: No NFS Transport Metrics
# ============================================================

# NFS xprt metrics do NOT appear for block driver
# (block driver automatically disables xprt metrics since it uses NVMe-oF)
# These metrics do not appear at all in vastblock output:
# - csi_node_nfs_xprt_total
# - csi_node_nfs_xprt_connected
# - csi_node_nfs_xprt_* (all xprt metrics)

# ============================================================
# CSI RPC Metrics (also available)
# ============================================================

# CSI operation counters
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeStageVolume",volume_id="pvc-abc123"} 1.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodePublishVolume",volume_id="pvc-abc123"} 1.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeUnpublishVolume",volume_id="pvc-abc123"} 1.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeUnstageVolume",volume_id="pvc-abc123"} 1.0
```

**Key Points:**

1. **NVMe Connect (2.3s):**
   - Initial connection to VAST NVMe subsystem
   - Falls in 1-5s bucket (normal range)
   - Happens once per volume attach

2. **Block Mount (0.15s):**
   - Very fast - just a bind mount of the NVMe device
   - Falls in <1s bucket (fast range)
   - `operation_type="block_mount"` distinguishes from NFS

3. **Block Unmount (0.08s):**
   - Even faster than mount
   - Falls in <1s bucket
   - Simple unmount operation

4. **No NFS xprt Metrics:**
   - Block driver automatically disables xprt metrics
   - `csi_node_nfs_xprt_*` metrics do NOT appear
   - This is correct behavior (block uses NVMe-oF, not NFS)

5. **Timing Comparison:**
   - NVMe connect: ~2-3 seconds (network + protocol handshake)
   - Block mount: ~0.1-0.2 seconds (local operation)
   - Block unmount: ~0.05-0.1 seconds (very fast)
   - Total overhead: ~2.5 seconds (mostly NVMe connect)

6. **Port Note:**
   - These metrics appear on port **9092** for vastblock
   - NFS driver uses port **9090**
   - Controller metrics on port **9093** (vs 9091 for NFS)

---

## Example 10: Block Driver - Multiple Volumes with Mixed Results

**Scenario:** Multiple block PVCs with some failures, showing realistic timing distribution.

**Setup:**
- 5 successful block volume mounts
- 1 failed NVMe connect (storage unreachable)
- 2 volumes unmounted

**Expected Output:**

```promql
# ============================================================
# NVMe Connect Operations (5 success, 1 failure)
# ============================================================

csi_node_nvme_connect_operations_total{node_name="worker-node-1",status="success"} 5.0
csi_node_nvme_connect_operations_total{node_name="worker-node-1",status="failure"} 1.0

# NVMe connect duration histogram (5 successful connects with varying times)
# TYPE csi_node_nvme_connect_duration_seconds histogram
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="1.0"} 1.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="5.0"} 4.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="20.0"} 5.0
csi_node_nvme_connect_duration_seconds_bucket{node_name="worker-node-1",le="+Inf"} 6.0
csi_node_nvme_connect_duration_seconds_sum{node_name="worker-node-1"} 47.8
csi_node_nvme_connect_duration_seconds_count{node_name="worker-node-1"} 6.0

# Analysis of above:
# - 1 connect in <1s (very fast, cached or local)
# - 3 connects in 1-5s range (normal)
# - 1 connect in 5-20s range (slow)
# - 1 connect took >20s (failed after timeout)
# - Average: 47.8s / 6 = 7.97s

# ============================================================
# Block Mount Operations (5 successful)
# ============================================================

csi_node_mount_operations_total{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",status="success"} 3.0
csi_node_mount_operations_total{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging",status="success"} 2.0

# Block mount duration histogram (all very fast - local operations)
# TYPE csi_node_mount_duration_seconds histogram
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="1.0"} 3.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="5.0"} 3.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="20.0"} 3.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="+Inf"} 3.0
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 0.421
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 3.0

csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging",le="1.0"} 2.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging",le="5.0"} 2.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging",le="20.0"} 2.0
csi_node_mount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging",le="+Inf"} 2.0
csi_node_mount_duration_seconds_sum{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging"} 0.315
csi_node_mount_duration_seconds_count{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="staging"} 2.0

# ============================================================
# Block Unmount Operations (2 unmounted so far)
# ============================================================

csi_node_umount_operations_total{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",status="success"} 2.0

# Unmount duration histogram (very fast)
# TYPE csi_node_umount_duration_seconds histogram
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="1.0"} 2.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="5.0"} 2.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="20.0"} 2.0
csi_node_umount_duration_seconds_bucket{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production",le="+Inf"} 2.0
csi_node_umount_duration_seconds_sum{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 0.165
csi_node_umount_duration_seconds_count{node_name="worker-node-1",operation_type="block_mount",pvc_namespace="production"} 2.0

# ============================================================
# CSI RPC Metrics (Block Driver)
# ============================================================

# CSI operation counters (full lifecycle per volume)
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeStageVolume"} 5.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodePublishVolume"} 5.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeUnpublishVolume"} 2.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="worker-node-1",method_name="NodeUnstageVolume"} 2.0

# Failed CSI operation (NVMe connect timeout)
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="DeadlineExceeded",hostname="worker-node-1",method_name="NodeStageVolume"} 1.0

# ============================================================
# WHAT'S MISSING: No NFS Transport Metrics
# ============================================================

# The following metrics do NOT appear for block driver:
# - csi_node_nfs_xprt_total (not present)
# - csi_node_nfs_xprt_connected (not present)
# - csi_node_nfs_xprt_pending_requests_total (not present)
# - csi_node_nfs_xprt_* (all xprt metrics not present)
#
# Reason: Block driver automatically disables NFS xprt metrics
```

**Key Points:**

1. **Histogram Buckets Show Distribution:**
   - 1 NVMe connect <1s (fast, possibly cached connection)
   - 3 NVMe connects in 1-5s (normal)
   - 1 NVMe connect in 5-20s (slow network)
   - 1 NVMe connect >20s (timeout/failure)

2. **Block Operations Are Fast:**
   - Mount: ~0.15s average (all in <1s bucket)
   - Unmount: ~0.08s average (all in <1s bucket)
   - Much faster than NFS operations

3. **Namespace Separation:**
   - Production: 3 mounts, 2 unmounts
   - Staging: 2 mounts, 0 unmounts
   - Helps identify which environment has issues

4. **Failure Handling:**
   - Failed NVMe connect still records duration (timeout)
   - CSI RPC shows `DeadlineExceeded` status
   - Counter increments with `status="failure"`

5. **Port Configuration:**
   - Metrics available on port **9092** (vastblock node)
   - Controller metrics on port **9093**
   - Different from NFS driver (9090/9091)

6. **Driver Identification:**
   - `driver_name="block.csi.vastdata.com"` in CSI RPC metrics
   - `operation_type="block_mount"` in mount metrics
   - No NFS-specific metrics (xprt) present

---

## Example 11: Block Driver Controller Metrics

**Scenario:** Controller metrics for block volume provisioning and deletion.

**Setup:**
- 3 volumes created (CreateVolume)
- 1 volume deleted (DeleteVolume)
- All operations successful

**Expected Output (port 9093):**

```promql
# ============================================================
# Controller CSI RPC Metrics
# ============================================================

# Volume creation operations
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume"} 3.0

# Volume creation duration histogram
# TYPE csi_plugin_operations_seconds histogram
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume",le="1.0"} 0.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume",le="5.0"} 2.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume",le="20.0"} 3.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume",le="+Inf"} 3.0
csi_plugin_operations_seconds_sum{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume"} 8.234
csi_plugin_operations_seconds_count{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="CreateVolume"} 3.0

# Volume deletion operations
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume"} 1.0

# Volume deletion duration histogram
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume",le="1.0"} 0.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume",le="5.0"} 1.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume",le="20.0"} 1.0
csi_plugin_operations_seconds_bucket{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume",le="+Inf"} 1.0
csi_plugin_operations_seconds_sum{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume"} 2.156
csi_plugin_operations_seconds_count{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="DeleteVolume"} 1.0

# Other controller operations
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="ControllerPublishVolume"} 3.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="ControllerUnpublishVolume"} 1.0
csi_plugin_operations_total{driver_name="block.csi.vastdata.com",grpc_status_code="OK",hostname="csi-controller-abc123",method_name="ValidateVolumeCapabilities"} 3.0
```

**Key Points:**

1. **Controller vs Node Metrics:**
   - Controller: CreateVolume, DeleteVolume, ControllerPublishVolume
   - Node: NodeStageVolume, NodePublishVolume, mount/umount operations
   - Controller has NO mount/umount/NVMe/xprt metrics

2. **CreateVolume Timing (2-3 seconds per volume):**
   - 0 volumes in <1s bucket
   - 2 volumes in 1-5s bucket (normal - API calls to VAST)
   - Average: 8.234s / 3 = 2.75s per volume

3. **DeleteVolume Timing (2.2 seconds):**
   - Falls in 1-5s bucket (normal)
   - Similar to CreateVolume (API overhead)

4. **Port Configuration:**
   - Controller metrics on port **9093** (vastblock)
   - Node metrics on port **9092** (vastblock)
   - Separate services for controller vs node

5. **Driver Name:**
   - `driver_name="block.csi.vastdata.com"`
   - Distinguishes from NFS driver (`csi.vastdata.com`)

6. **No Node-Specific Metrics:**
   - Controller doesn't have mount/umount metrics
   - No NVMe connect metrics on controller
   - No NFS xprt metrics on controller

---

## Example 12: Health Check Endpoint

**Scenario:** Test the `/health` endpoint.

**Command:**
```bash
curl -s http://localhost:9090/health
```

**Expected Output:**

```json
{
  "status": "ok",
  "timestamp": "2026-02-10T14:30:15Z"
}
```

**Key Points:**
- Simple health check for liveness/readiness probes
- Always returns 200 OK if metrics server is running
- Can be used in Kubernetes probes

---

## Filtering Verification Examples

### Example 11: Local Transport (Should NOT Appear)

**Scenario:** System creates NFS mount to `127.0.0.1` (not CSI-related).

**Expected:** This transport should be **filtered out** and **not appear** in metrics.

**Verification:**
```bash
# Check kernel xprt entries
sudo cat /sys/kernel/sunrpc/xprt-switches/switch-*/xprt-*/info | grep -A1 "dstaddr"
# Output might show: dstaddr=127.0.0.1:2049

# Check metrics (should NOT include 127.0.0.1)
curl -s http://localhost:9090/metrics | grep destination
# Should NOT see: destination="127.0.0.1"
```

**Expected Result:** No metrics with `destination="127.0.0.1"` or `destination="localhost"`.

---

### Example 12: CLOSED Transport (Should NOT Appear)

**Scenario:** After unmount, kernel keeps xprt entry in CLOSED state for a while.

**Verification:**
```bash
# Check kernel xprt state
sudo cat /sys/kernel/sunrpc/xprt-switches/switch-*/xprt-*/state
# Output might show: state=CLOSED

# Check metrics
curl -s http://localhost:9090/metrics | grep xprt_total
```

**Expected Result:** `xprt_total` should NOT count CLOSED transports.

---

### Example 13: Unknown Destination (Should NOT Appear)

**Scenario:** Corrupt xprt entry with missing destination.

**Expected:** Transport should be filtered out.

**Verification:**
```bash
# Check if any xprt entries have missing dstaddr
sudo cat /sys/kernel/sunrpc/xprt-switches/switch-*/xprt-*/info | grep "dstaddr" || echo "missing"

# Check metrics
curl -s http://localhost:9090/metrics | grep 'destination="unknown"'
```

**Expected Result:** No metrics with `destination="unknown"`.

---

## Quick Test Script

Save this as `test_metrics_output.sh`:

```bash
#!/bin/bash
set -e

echo "=== CSI Metrics Output Test ==="
echo

# Find CSI node pod
POD=$(kubectl get pod -n vast-csi -l app=csi-vast-node -o jsonpath='{.items[0].metadata.name}')
echo "Found pod: $POD"
echo

# Port-forward (background process)
kubectl port-forward -n vast-csi "$POD" 9090:9090 >/dev/null 2>&1 &
PF_PID=$!
sleep 2

# Cleanup on exit
trap "kill $PF_PID 2>/dev/null || true" EXIT

# Fetch metrics
echo "=== Fetching metrics ==="
curl -s http://localhost:9090/metrics | grep "^csi_node"

echo
echo "=== Health check ==="
curl -s http://localhost:9090/health | jq .

echo
echo "=== Summary ==="
echo "Mount operations:"
curl -s http://localhost:9090/metrics | grep "csi_node_mount_operations_total" | grep -v "#"
echo
echo "Unmount operations:"
curl -s http://localhost:9090/metrics | grep "csi_node_umount_operations_total" | grep -v "#"
echo
echo "Active transports:"
curl -s http://localhost:9090/metrics | grep "csi_node_nfs_xprt_total" | grep -v "#"
echo
echo "Destinations:"
curl -s http://localhost:9090/metrics | grep "destination=" | grep -v "#" | cut -d'{' -f2 | cut -d'}' -f1 | sort -u
```

Make it executable and run:

```bash
chmod +x test_metrics_output.sh
./test_metrics_output.sh
```

---

## Prometheus Query Examples

Once metrics are scraped into Prometheus, you can use these queries:

```promql
# Mount success rate (last 5 minutes)
rate(csi_node_mount_operations_total{status="success"}[5m])
/ rate(csi_node_mount_operations_total[5m])

# Average mount duration by namespace
rate(csi_node_mount_duration_seconds_sum[5m])
/ rate(csi_node_mount_duration_seconds_count[5m])
by (pvc_namespace)

# P95 mount duration
histogram_quantile(0.95, rate(csi_node_mount_duration_seconds_bucket[5m]))

# Failed mounts in last hour
increase(csi_node_mount_operations_total{status="failure"}[1h])

# Unhealthy transports
sum(csi_node_nfs_xprt_unhealthy)

# Congested destinations
csi_node_nfs_xprt_congested_state == 1

# Pending requests by destination
topk(5, csi_node_nfs_xprt_pending_requests)
```

---

## Grafana Dashboard Query Examples

For creating Grafana dashboards:

```promql
# Panel 1: Mount Operations (Counter)
sum(rate(csi_node_mount_operations_total[5m])) by (status)

# Panel 2: Mount Duration (Heatmap)
sum(rate(csi_node_mount_duration_seconds_bucket[5m])) by (le)

# Panel 3: Active Transports (Gauge)
sum(csi_node_nfs_xprt_total)

# Panel 4: Transport Health (Gauge)
sum(csi_node_nfs_xprt_connected) /
sum(csi_node_nfs_xprt_total) * 100

# Panel 5: Top Namespaces by Mount Volume
topk(10, sum(rate(csi_node_mount_operations_total[5m])) by (pvc_namespace))

# Panel 6: Pending Requests Timeline
sum(csi_node_nfs_xprt_pending_requests_total)
```

---

## Troubleshooting Metrics Output

### Problem: No metrics appearing

**Check:**
```bash
# Is metrics enabled?
kubectl get pod -n vast-csi <pod> -o yaml | grep X_CSI_METRICS_ENABLED
# Should show: value: "true"

# Is port exposed?
kubectl get pod -n vast-csi <pod> -o yaml | grep "containerPort: 9090"

# Can you reach the endpoint?
kubectl exec -n vast-csi <pod> -- curl -s http://localhost:9090/health
```

---

### Problem: Per-destination metrics not appearing

**Possible causes:**
1. All transports are CLOSED (expected - they're filtered out)
2. All transports are to localhost (expected - filtered out)
3. No volumes are mounted (expected - no transports exist)

**Check:**
```bash
# Are there any active transports in the kernel?
kubectl exec -n vast-csi <pod> -- find /sys/kernel/sunrpc/xprt-switches -name "xprt-*" -type d

# What are their states?
kubectl exec -n vast-csi <pod> -- cat /sys/kernel/sunrpc/xprt-switches/switch-*/xprt-*/state
```

---

### Problem: Metrics show "unknown" labels

**Example:**
```
csi_node_mount_operations_total{node_name="unknown",pvc_namespace="unknown",...}
```

**Cause:** Environment variables not set in pod.

**Fix:**
```bash
# Check if NODE_NAME is set
kubectl exec -n vast-csi <pod> -- env | grep NODE_NAME
# Should show: NODE_NAME=worker-node-1

# If not set, update Helm chart (should be fixed in v2.6)
```
