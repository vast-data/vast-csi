# CSI Metrics – Usage Guide

This guide explains how to enable and scrape Prometheus metrics from the VAST CSI driver (both node and controller), whether you use **Prometheus Operator** or **Prometheus manually**.

---

## What is exposed

The VAST CSI driver exposes metrics from two types of services:

### Node Metrics (DaemonSet pods)

When node metrics are enabled, each CSI node pod serves:

| Endpoint   | Purpose |
|-----------|---------|
| `GET /metrics` | Prometheus exposition format (counters, histograms, gauges) |
| `GET /health`  | Health check (e.g. for Kubernetes liveness/readiness)     |

**Node metric families:**

- **CSI RPC Operations:** `csi_plugin_operations_total`, `csi_plugin_operations_seconds`
  - Tracks all CSI gRPC method calls (NodeStageVolume, NodePublishVolume, etc.)
  - Labels: `driver_name`, `method_name`, `grpc_status_code`, `hostname`, `volume_id`
- **Mount/umount:** `csi_node_mount_operations_total`, `csi_node_mount_duration_seconds`, `csi_node_umount_operations_total`, `csi_node_umount_duration_seconds`
  - Labels: `operation_type`, `status`, `hostname`
- **NVMe connect:** `csi_node_nvme_connect_operations_total`, `csi_node_nvme_connect_duration_seconds`
  - Labels: `status`, `hostname`
- **NFS transport (xprt):** `csi_node_nfs_xprt_total`, `csi_node_nfs_xprt_connected`, per-destination gauges, etc.
  - Labels vary by metric (aggregate metrics have no labels, per-transport metrics have `destination`)

### Controller Metrics (Deployment/StatefulSet pods)

When controller metrics are enabled, each CSI controller pod serves:

| Endpoint   | Purpose |
|-----------|---------|
| `GET /metrics` | Prometheus exposition format (counters, histograms, gauges) |
| `GET /health`  | Health check (e.g. for Kubernetes liveness/readiness)     |

**Controller metric families:**

- **CSI RPC Operations:** `csi_plugin_operations_total`, `csi_plugin_operations_seconds`
  - Tracks all CSI gRPC method calls (CreateVolume, DeleteVolume, ControllerPublishVolume, etc.)
  - Labels: `driver_name`, `method_name`, `grpc_status_code`, `hostname`, `volume_id`

**Note:** Controller metrics only include CSI RPC operations. Node-specific metrics (mount/umount, NVMe, NFS xprt) are not available on the controller.

---

## Step 1: Enable metrics in the chart

Metrics are **disabled by default** for both node and controller. Enable them when installing or upgrading the Helm release.

### vastcsi (NFS driver)

```yaml
# values.yaml or --set
node:
  metrics:
    enabled: true
    port: 9090   # default

controller:
  metrics:
    enabled: true  # optional, separate from node metrics
    port: 9091     # default
```

### vastblock (block driver)

```yaml
node:
  metrics:
    enabled: true
    port: 9090   # default (unified with vastcsi)

controller:
  metrics:
    enabled: true  # optional, separate from node metrics
    port: 9091     # default (unified with vastcsi)
```

**Helm install example:**

```bash
# NFS driver - node metrics only
helm install vastcsi ./charts/vastcsi -n vast-csi --create-namespace \
  --set node.metrics.enabled=true

# NFS driver - both node and controller metrics
helm install vastcsi ./charts/vastcsi -n vast-csi --create-namespace \
  --set node.metrics.enabled=true \
  --set controller.metrics.enabled=true

# Block driver - both node and controller metrics
helm install vastblock ./charts/vastblock -n vast-csi --create-namespace \
  --set node.metrics.enabled=true \
  --set controller.metrics.enabled=true
```

After this:
- The CSI node DaemonSet pods expose the node metrics port (9090), and a **headless Service** is created for discovery
- The CSI controller Deployment/StatefulSet pods expose the controller metrics port (9091), and a **headless Service** is created for discovery

---

## Option A: Using Prometheus Operator (ServiceMonitor)

Use this if your cluster runs **Prometheus Operator** (e.g. kube-prometheus-stack, prometheus-operator Helm chart).

**Reference:** [ServiceMonitor (Prometheus Operator API)](https://prometheus-operator.dev/docs/operator/api/#servicemonitor) – CRD that tells Prometheus to scrape a Kubernetes Service.

### 1. Enable ServiceMonitor in the CSI chart

**vastcsi:**

```yaml
node:
  metrics:
    enabled: true
    port: 9090
    serviceMonitor:
      enabled: true
      interval: 30s
      # Optional: add labels so your Prometheus instance selects this ServiceMonitor
      # labels:
      #   release: prometheus   # if Prometheus selects by release label

controller:
  metrics:
    enabled: true  # optional
    port: 9091
    serviceMonitor:
      enabled: true
      interval: 30s
      # labels:
      #   release: prometheus
```

**vastblock:**

```yaml
node:
  metrics:
    enabled: true
    port: 9090
    serviceMonitor:
      enabled: true
      interval: 30s

controller:
  metrics:
    enabled: true  # optional
    port: 9091
    serviceMonitor:
      enabled: true
      interval: 30s
```

### 2. Ensure Prometheus selects the ServiceMonitor

Your Prometheus CR (or Helm values) must select ServiceMonitors in the namespace where the CSI driver is installed. For example, with **kube-prometheus-stack**:

```yaml
# Prometheus should have a serviceMonitorNamespaceSelector (or equivalent) that includes the CSI namespace
# and serviceMonitorSelector that matches the ServiceMonitor labels you set.
```

If you use the default `labels: {}`, the stack's default Prometheus often selects all ServiceMonitors. If not, add a label (e.g. `release: prometheus`) to both `node.metrics.serviceMonitor.labels` and `controller.metrics.serviceMonitor.labels`, and set the same in your Prometheus `serviceMonitorSelector`.

### 3. Verify

1. List ServiceMonitors in the CSI namespace:
   ```bash
   kubectl get servicemonitor -n vast-csi
   ```
   You should see ServiceMonitors for both node and controller (if enabled).

2. In Prometheus UI → **Status → Targets**, search for jobs scraping the CSI metrics:
   - Node: e.g. `serviceMonitor/vast-csi/release-name-vast-node-metrics/0`
   - Controller: e.g. `serviceMonitor/vast-csi/release-name-vast-controller-metrics/0`
   
   Targets should be **UP**.

---

## Option B: Using Prometheus manually (no Operator)

Use this if you run **vanilla Prometheus** (e.g. your own config and deployment, no ServiceMonitor CRD). ServiceMonitor is a Prometheus Operator CRD; if you don't use the Operator, ignore it and use scrape configs below.

### 1. Do not enable ServiceMonitor

Leave `node.metrics.serviceMonitor.enabled: false` and `controller.metrics.serviceMonitor.enabled: false` (default). Only `node.metrics.enabled: true` and/or `controller.metrics.enabled: true` are needed.

### 2. Add scrape configs to Prometheus

Add jobs that discover the CSI node and controller pods (or the headless Services). Two common patterns:

**Pattern 1: Scrape via the headless Services (one target per pod)**

Prometheus discovers endpoints for the headless Services. Use **relabeling** to set `__address__` to pod IP and metrics port.

```yaml
# prometheus.yml (or your config)
scrape_configs:
  # Node metrics (vastcsi)
  - job_name: 'csi-node-metrics-vastcsi'
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names: [vast-csi]
    relabel_configs:
      # Only keep endpoints that belong to the CSI node metrics service
      - source_labels: [__meta_kubernetes_service_name]
        regex: .+-vast-node-metrics
        action: keep
      - source_labels: [__meta_kubernetes_endpoint_port_name]
        regex: metrics
        action: keep
      - source_labels: [__meta_kubernetes_pod_ip]
        target_label: __address__
        replacement: ${1}:9090
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
      - source_labels: [__meta_kubernetes_pod_node_name]
        target_label: node
    metric_relabel_configs: []

  # Controller metrics (vastcsi)
  - job_name: 'csi-controller-metrics-vastcsi'
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names: [vast-csi]
    relabel_configs:
      # Only keep endpoints that belong to the CSI controller metrics service
      - source_labels: [__meta_kubernetes_service_name]
        regex: .+-vast-controller-metrics
        action: keep
      - source_labels: [__meta_kubernetes_endpoint_port_name]
        regex: metrics
        action: keep
      - source_labels: [__meta_kubernetes_pod_ip]
        target_label: __address__
        replacement: ${1}:9091
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
    metric_relabel_configs: []
```

For **vastblock**, use the same idea with separate jobs (or combine using more sophisticated relabeling).

**Pattern 2: Static list (if you have a fixed set of nodes or FQDN)**

If you prefer a static list of targets (e.g. you know the Service DNS names):

```yaml
scrape_configs:
  - job_name: 'csi-node-metrics-vastcsi'
    static_configs:
      - targets:
          - 'release-name-vast-node-metrics.vast-csi.svc.cluster.local:9090'

  - job_name: 'csi-controller-metrics-vastcsi'
    static_configs:
      - targets:
          - 'release-name-vast-controller-metrics.vast-csi.svc.cluster.local:9091'
```

For **vanilla Prometheus in Kubernetes**, `kubernetes_sd_configs` (pattern 1) is usually the right approach so all node pods are scraped.

### 3. Verify

1. Reload or restart Prometheus so it picks up the new config.
2. **Status → Targets**: the jobs `csi-node-metrics-vastcsi` and `csi-controller-metrics-vastcsi` should list targets in state **UP**.
3. **Graph**: run queries such as `csi_plugin_operations_total` or `csi_node_mount_operations_total` to confirm data.

---

## Quick check without Prometheus

To confirm the metrics endpoints work from inside the cluster:

```bash
# For node metrics
kubectl get pods -n vast-csi -l app.kubernetes.io/component=csi-node
kubectl port-forward -n vast-csi pod/<csi-node-pod-name> 9090:9090
curl -s http://localhost:9090/metrics | head -50
curl -s http://localhost:9090/health

# For controller metrics
kubectl get pods -n vast-csi -l app.kubernetes.io/component=csi-controller
kubectl port-forward -n vast-csi pod/<csi-controller-pod-name> 9091:9091
curl -s http://localhost:9091/metrics | head -50
curl -s http://localhost:9091/health
```

---

## Example PromQL Queries

### Node Metrics Queries

With the `hostname` label, you can answer specific questions:

```promql
# Which node has mount failures?
sum(rate(csi_node_mount_operations_total{status="failure"}[5m]))
  by (hostname)

# Which node has mount issues?
sum(rate(csi_node_mount_operations_total{status!="success"}[5m]))
  by (hostname)

# Average mount duration by node
rate(csi_node_mount_duration_seconds_sum[5m])
/ rate(csi_node_mount_duration_seconds_count[5m])
by (hostname)

# Total mount success rate
rate(csi_node_mount_operations_total{status="success"}[5m])
/ rate(csi_node_mount_operations_total[5m])

# Mount timeouts by operation type
sum(rate(csi_node_mount_operations_total{status="timeout"}[5m]))
  by (operation_type)

# NFS xprt health issues
csi_node_nfs_xprt_unhealthy > 0
```

### CSI RPC Metrics Queries (Node and Controller)

```promql
# Total CSI operations by method
sum(rate(csi_plugin_operations_total[5m])) by (method_name)

# CSI operations by gRPC status code
sum(rate(csi_plugin_operations_total[5m])) by (grpc_status_code)

# CSI operation failures
sum(rate(csi_plugin_operations_total{grpc_status_code!="OK"}[5m])) 
  by (method_name, grpc_status_code)

# Average CSI operation duration (p50, p95, p99)
histogram_quantile(0.50, 
  sum(rate(csi_plugin_operations_seconds_bucket[5m])) by (method_name, le)
)
histogram_quantile(0.95, 
  sum(rate(csi_plugin_operations_seconds_bucket[5m])) by (method_name, le)
)
histogram_quantile(0.99, 
  sum(rate(csi_plugin_operations_seconds_bucket[5m])) by (method_name, le)
)

# Slow CSI operations (>10 seconds)
sum(rate(csi_plugin_operations_seconds_bucket{le="10.0"}[5m])) by (method_name)
- sum(rate(csi_plugin_operations_seconds_bucket{le="5.0"}[5m])) by (method_name)

# Controller-specific: Volume creation rate
rate(csi_plugin_operations_total{method_name="CreateVolume",grpc_status_code="OK"}[5m])

# Controller-specific: Volume deletion failures
rate(csi_plugin_operations_total{method_name="DeleteVolume",grpc_status_code!="OK"}[5m])
```

---

## Summary

| Scenario                     | Chart: `node.metrics.enabled` | Chart: `controller.metrics.enabled` | Chart: ServiceMonitor enabled | You configure |
|-----------------------------|--------------------------------|--------------------------------------|-------------------------------|----------------|
| **Prometheus Operator (node only)**     | `true`                         | `false`                              | `node: true`                  | Prometheus selects ServiceMonitors in CSI namespace |
| **Prometheus Operator (both)**          | `true`                         | `true`                               | `node: true, controller: true` | Prometheus selects ServiceMonitors in CSI namespace |
| **Prometheus manually (node only)**     | `true`                         | `false`                              | `false`                       | Add `scrape_configs` job for node |
| **Prometheus manually (both)**          | `true`                         | `true`                               | `false`                       | Add `scrape_configs` jobs for node and controller |

In all cases, the CSI pods expose the same `/metrics` and `/health` endpoints; only how Prometheus discovers and scrapes the targets differs (ServiceMonitor vs manual scrape config).
