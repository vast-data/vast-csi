# CSI Node Metrics – Usage Guide

This guide explains how to enable and scrape Prometheus metrics from the VAST CSI node, whether you use **Prometheus Operator** or **Prometheus manually**.

---

## What is exposed

When metrics are enabled, each CSI node pod serves:

| Endpoint   | Purpose |
|-----------|---------|
| `GET /metrics` | Prometheus exposition format (counters, histograms, gauges) |
| `GET /health`  | Health check (e.g. for Kubernetes liveness/readiness)     |

**Metric families** (see [METRICS.md](../METRICS.md) if present, or `vast_csi/metrics.py`):

- **Mount/umount:** `csi_node_mount_operations_total`, `csi_node_mount_duration_seconds`, `csi_node_umount_operations_total`, `csi_node_umount_duration_seconds`
- **NVMe connect:** `csi_node_nvme_connect_operations_total`, `csi_node_nvme_connect_duration_seconds`
- **NFS transport (xprt):** `csi_node_nfs_xprt_total`, `csi_node_nfs_xprt_connected`, per-destination gauges, etc.

---

## Step 1: Enable metrics in the chart

Metrics are **disabled by default**. Enable them when installing or upgrading the Helm release.

### vastcsi (NFS driver)

```yaml
# values.yaml or --set
node:
  metrics:
    enabled: true
    port: 9090   # default
```

### vastblock (block driver)

```yaml
node:
  metrics:
    enabled: true
    port: 9091   # default (different from vastcsi to avoid port clash)
```

**Helm install example:**

```bash
# NFS driver
helm install vastcsi ./charts/vastcsi -n vast-csi --create-namespace \
  --set node.metrics.enabled=true

# Block driver
helm install vastblock ./charts/vastblock -n vast-csi --create-namespace \
  --set node.metrics.enabled=true
```

After this, the CSI node DaemonSet pods expose the metrics port, and a **headless Service** is created so Prometheus can discover the pods (e.g. `release-name-vast-node-metrics.<namespace>.svc.cluster.local`).

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
```

**vastblock:**

```yaml
node:
  metrics:
    enabled: true
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

If you use the default `labels: {}`, the stack’s default Prometheus often selects all ServiceMonitors. If not, add a label (e.g. `release: prometheus`) to `serviceMonitor.labels` and set the same in your Prometheus `serviceMonitorSelector`.

### 3. Verify

1. List ServiceMonitors in the CSI namespace:
   ```bash
   kubectl get servicemonitor -n vast-csi
   ```
2. In Prometheus UI → **Status → Targets**, search for a job scraping the CSI metrics (e.g. `serviceMonitor/vast-csi/release-name-vast-node-metrics/0`). Target should be **UP**.

---

## Option B: Using Prometheus manually (no Operator)

Use this if you run **vanilla Prometheus** (e.g. your own config and deployment, no ServiceMonitor CRD). ServiceMonitor is a Prometheus Operator CRD; if you don’t use the Operator, ignore it and use scrape configs below.

### 1. Do not enable ServiceMonitor

Leave `node.metrics.serviceMonitor.enabled: false` (default). Only `node.metrics.enabled: true` is needed.

### 2. Add a scrape config to Prometheus

Add a job that discovers the CSI node pods (or the headless Service). Two common patterns:

**Pattern 1: Scrape via the headless Service (one target per pod)**

Prometheus discovers endpoints for the headless Service. Use **relabeling** to set `__address__` to pod IP and metrics port.

```yaml
# prometheus.yml (or your config)
scrape_configs:
  - job_name: 'csi-node-metrics-vastcsi'
    kubernetes_sd_configs:
      - role: endpoints
        namespaces:
          names: [vast-csi]
    relabel_configs:
      # Only keep endpoints that belong to the CSI metrics service
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
```

For **vastblock**, use the same idea but set the port to **9091** in the replacement (e.g. `${1}:9091`), or use a separate job with a label/name that matches the block driver’s metrics service.

**Pattern 2: Static list (if you have a fixed set of nodes or FQDN)**

If you prefer a static list of targets (e.g. you know the Service DNS name):

```yaml
scrape_configs:
  - job_name: 'csi-node-metrics-vastcsi'
    static_configs:
      - targets:
          - 'release-name-vast-node-metrics.vast-csi.svc.cluster.local:9090'
    # For a headless Service, this will resolve to multiple pod IPs if you use dns_sd_configs
    # For a single endpoint you may need to use kubernetes_sd_configs as above
```

For **vanilla Prometheus in Kubernetes**, `kubernetes_sd_configs` (pattern 1) is usually the right approach so all node pods are scraped.

### 3. Verify

1. Reload or restart Prometheus so it picks up the new config.
2. **Status → Targets**: the job `csi-node-metrics-vastcsi` (and optionally a similar job for vastblock) should list targets in state **UP**.
3. **Graph**: run a query such as `csi_node_mount_operations_total` to confirm data.

---

## Quick check without Prometheus

To confirm the metrics endpoint works from inside the cluster:

```bash
# Pick a CSI node pod
kubectl get pods -n vast-csi -l app.kubernetes.io/component=csi-node  # adjust labels if needed

# Port-forward and curl (vastcsi port 9090, vastblock 9091)
kubectl port-forward -n vast-csi pod/<csi-node-pod-name> 9090:9090

# In another terminal
curl -s http://localhost:9090/metrics | head -50
curl -s http://localhost:9090/health
```

---

## Summary

| Scenario                     | Chart: `node.metrics.enabled` | Chart: `node.metrics.serviceMonitor.enabled` | You configure |
|-----------------------------|--------------------------------|-----------------------------------------------|----------------|
| **Prometheus Operator**     | `true`                         | `true`                                        | Prometheus selects ServiceMonitors in CSI namespace |
| **Prometheus manually**     | `true`                         | `false`                                       | Add `scrape_configs` job (e.g. `kubernetes_sd_configs` + relabeling) |

In both cases, the CSI node exposes the same `/metrics` and `/health`; only how Prometheus discovers and scrapes the targets differs (ServiceMonitor vs manual scrape config).
