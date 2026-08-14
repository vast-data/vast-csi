"""
Background resource sampler for CSI pod containers.

Uses the kubelet /metrics/cadvisor Prometheus endpoint (cAdvisor at 1-second
internal resolution) instead of the Summary API which has a 10-second cache
and misses short spikes from mkfs/fsck operations.

CPU is derived from counter deltas: (cpu_seconds_delta / time_delta) × 1000 m.
Memory is read directly from the gauge.

After a test, call :meth:`ResourceSampler.report` to print avg/peak/spike table.
Pod restart events are tracked separately to detect OOM kills / evictions.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import NamedTuple

from lib.logging import logger

from lib.constants import CSI_NAMESPACE

# Metric names from cAdvisor Prometheus exposition.
_CPU_METRIC = "container_cpu_usage_seconds_total"
_MEM_METRIC = "container_memory_working_set_bytes"
_RESTART_METRIC = "kube_pod_container_status_restarts_total"  # from kube-state-metrics if present
# Fallback restart detection via pod status (used when kube-state-metrics absent)

_METRIC_LINE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([\d.eE+\-]+)')
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')

# Spike threshold defaults — flag samples exceeding these.
_SPIKE_CPU_MILLIS = 500.0   # 0.5 cores
_SPIKE_MEM_MIB = 500.0      # 500 MiB


class _Sample(NamedTuple):
    ts: float
    pod: str
    container: str
    cpu_millis: float   # instantaneous millicores
    mem_mib: float      # working-set MiB
    is_spike: bool      # cpu > threshold OR mem > threshold


@dataclass
class ResourceSampler:
    """
    Sample per-container CPU & memory from the kubelet cAdvisor endpoint.

    Sampling interval defaults to 1 second for spike-level granularity.
    CPU is computed as a rate from ``container_cpu_usage_seconds_total`` counter
    deltas, giving true instantaneous CPU regardless of the kubelet Summary cache.

    Usage::

        sampler = ResourceSampler(k8s.kubectl)
        sampler.start()
        run_test(...)
        sampler.stop()
        sampler.report("run_block_basic_pvc_and_pod")
    """

    kubectl: object                              # plumbum bound command
    namespace: str = CSI_NAMESPACE
    interval_sec: float = 0.5                   # matches kubelet housekeeping-interval=500ms in setup_k3s_cluster.sh
    spike_cpu_millis: float = _SPIKE_CPU_MILLIS
    spike_mem_mib: float = _SPIKE_MEM_MIB

    _samples: list[_Sample] = field(default_factory=list, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _node_name: str | None = field(default=None, init=False, repr=False)
    # (pod, container) → (ts, cpu_seconds) at the last counter CHANGE.
    # Only updated when counter advances; prevents false spikes from stale cAdvisor cache.
    _prev_cpu: dict[tuple[str, str], tuple[float, float]] = field(
        default_factory=dict, init=False, repr=False
    )
    # pod → restart count at start, for eviction/OOM detection
    _initial_restarts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    # live reporting thread (optional, started by start_live_reporting)
    _live_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _live_interval_sec: float | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._samples.clear()
        self._prev_cpu.clear()
        self._initial_restarts.clear()
        self._node_name = self._discover_node()
        if not self._node_name:
            logger.warning("ResourceSampler: could not discover k8s node — metrics disabled")
            return
        self._initial_restarts = self._get_restart_counts()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="resource-sampler"
        )
        self._thread.start()

    def start_live_reporting(self, interval_sec: float = 5.0) -> None:
        """Start printing a live windowed snapshot every interval_sec seconds.

        Can be called at any time after :meth:`start`. Each live report shows
        only samples from the last *interval_sec* window so values reflect
        current load, not the entire test history.
        """
        self._live_interval_sec = interval_sec
        if self._thread is not None and self._live_thread is None:
            self._live_thread = threading.Thread(
                target=self._live_report_loop, daemon=True, name="resource-sampler-live"
            )
            self._live_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._live_thread:
            self._live_thread.join(timeout=(self._live_interval_sec or 5) + 2)
            self._live_thread = None
        if self._thread:
            self._thread.join(timeout=self.interval_sec + 5)
            self._thread = None

    def report(self, test_name: str = "") -> None:
        """Log avg/peak/spike CPU & memory per container, plus restart events."""
        title = f"Resource utilization — {test_name}" if test_name else "Resource utilization"

        if not self._samples:
            logger.info(f"ResourceSampler: no samples collected for {test_name!r}")
            return

        groups: dict[tuple[str, str], list[_Sample]] = defaultdict(list)
        for s in self._samples:
            groups[(s.pod, s.container)].append(s)

        pod_w = max((len(k[0]) for k in groups), default=4) + 2
        ctr_w = max((len(k[1]) for k in groups), default=10) + 2
        pod_w = max(pod_w, 6)
        ctr_w = max(ctr_w, 12)

        header = (
            f"{'Pod':<{pod_w}} {'Container':<{ctr_w}}"
            f" {'CPU avg':>9} {'CPU peak':>9}"
            f" {'Mem avg':>9} {'Mem peak':>9}"
            f" {'Spikes':>7} {'Samples':>8}"
        )
        sep = "─" * len(header)
        rows = [sep, title, sep, header, sep]

        for (pod, container), samples in sorted(groups.items()):
            cpus = [s.cpu_millis for s in samples]
            mems = [s.mem_mib for s in samples]
            spikes = sum(1 for s in samples if s.is_spike)
            rows.append(
                f"{pod:<{pod_w}} {container:<{ctr_w}}"
                f" {sum(cpus)/len(cpus):>8.1f}m {max(cpus):>8.1f}m"
                f" {sum(mems)/len(mems):>8.1f}M {max(mems):>8.1f}M"
                f" {spikes:>7} {len(samples):>8}"
            )

        rows.append(sep)
        rows.append(
            f"  Spike threshold: CPU > {self.spike_cpu_millis:.0f}m  |"
            f"  Mem > {self.spike_mem_mib:.0f}Mi  |  Sample interval: {self.interval_sec}s"
            f"  |  Pods: *vast-node / *vast-controller"
        )

        # Restart / eviction summary.
        final_restarts = self._get_restart_counts()
        restart_deltas = {
            pod: final_restarts.get(pod, 0) - self._initial_restarts.get(pod, 0)
            for pod in set(final_restarts) | set(self._initial_restarts)
        }
        restart_events = {pod: delta for pod, delta in restart_deltas.items() if delta > 0}
        if restart_events:
            rows.append("")
            rows.append("  ⚠  Container restarts detected during test (possible OOM / eviction):")
            for pod, delta in sorted(restart_events.items()):
                rows.append(f"       {pod}: +{delta} restart(s)")
        else:
            rows.append("  ✓  No container restarts detected")

        rows.append(sep)
        logger.info("\n" + "\n".join(rows))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_node(self) -> str | None:
        try:
            import json
            raw = self.kubectl("get", "nodes", "-o", "json")
            items = json.loads(raw).get("items", [])
            if items:
                return items[0]["metadata"]["name"]
        except Exception as exc:
            logger.warning(f"ResourceSampler: node discovery failed: {exc}")
        return None

    def _fetch_cadvisor(self) -> str:
        path = f"/api/v1/nodes/{self._node_name}/proxy/metrics/cadvisor"
        return self.kubectl("get", "--raw", path)

    def _parse_cadvisor(self, text: str) -> tuple[
        dict[tuple[str, str], float],   # (pod, container) → cpu_seconds counter
        dict[tuple[str, str], float],   # (pod, container) → mem bytes
    ]:
        cpu_counters: dict[tuple[str, str], float] = {}
        mem_gauges: dict[tuple[str, str], float] = {}

        for line in text.splitlines():
            if line.startswith("#"):
                continue
            m = _METRIC_LINE_RE.match(line)
            if not m:
                continue
            metric_name = m.group(1)
            if metric_name not in (_CPU_METRIC, _MEM_METRIC):
                continue
            labels = dict(_LABEL_RE.findall(m.group(2)))
            if labels.get("namespace") != self.namespace:
                continue
            pod = labels.get("pod", "")
            container = labels.get("container", "")
            if not pod or not container:
                continue
            if not any(lbl in pod for lbl in ("vast-node", "vast-controller")):
                continue
            try:
                value = float(m.group(3))
            except ValueError:
                continue

            key = (pod, container)
            if metric_name == _CPU_METRIC:
                # Keep the max if there are duplicate label sets (shouldn't happen, but defensive).
                cpu_counters[key] = max(cpu_counters.get(key, 0.0), value)
            else:
                mem_gauges[key] = value

        return cpu_counters, mem_gauges

    def _sample_once(self) -> None:
        now = time.monotonic()
        try:
            text = self._fetch_cadvisor()
        except Exception as exc:
            logger.debug(f"ResourceSampler: cadvisor fetch failed: {exc}")
            return

        cpu_counters, mem_gauges = self._parse_cadvisor(text)

        for key, cpu_counter in cpu_counters.items():
            pod, container = key
            mem_bytes = mem_gauges.get(key, 0.0)
            mem_mib = mem_bytes / (1024 * 1024)

            prev = self._prev_cpu.get(key)

            if prev is None:
                # Warm up: record first counter value, no sample yet.
                self._prev_cpu[key] = (now, cpu_counter)
                continue

            prev_ts, prev_counter = prev
            if cpu_counter == prev_counter:
                # cAdvisor hasn't refreshed its cgroup read yet — skip to avoid
                # false spike when the counter finally advances (delta/0.5s inflated).
                continue

            dt = now - prev_ts
            if dt <= 0:
                continue
            cpu_millis = ((cpu_counter - prev_counter) / dt) * 1000.0
            cpu_millis = max(0.0, cpu_millis)  # defensive: counter resets are rare but possible
            self._prev_cpu[key] = (now, cpu_counter)

            is_spike = cpu_millis > self.spike_cpu_millis or mem_mib > self.spike_mem_mib
            self._samples.append(_Sample(
                ts=now,
                pod=pod,
                container=container,
                cpu_millis=cpu_millis,
                mem_mib=mem_mib,
                is_spike=is_spike,
            ))

    def _get_restart_counts(self) -> dict[str, int]:
        """Return {pod_name: total_restart_count} for CSI namespace pods."""
        try:
            import json
            raw = self.kubectl("get", "pods", "-n", self.namespace, "-o", "json")
            pods = json.loads(raw).get("items", [])
            counts: dict[str, int] = {}
            for pod in pods:
                name = pod["metadata"]["name"]
                restarts = sum(
                    cs.get("restartCount", 0)
                    for cs in pod.get("status", {}).get("containerStatuses", [])
                )
                counts[name] = restarts
            return counts
        except Exception:
            return {}

    def _live_report_loop(self) -> None:
        while not self._stop.wait(self._live_interval_sec):
            self._report_window(self._live_interval_sec)

    def _report_window(self, window_sec: float) -> None:
        """Print a snapshot covering only the last window_sec of samples."""
        cutoff = time.monotonic() - window_sec
        samples = [s for s in self._samples if s.ts >= cutoff]
        if not samples:
            return

        groups: dict[tuple[str, str], list[_Sample]] = defaultdict(list)
        for s in samples:
            groups[(s.pod, s.container)].append(s)

        pod_w = max((len(k[0]) for k in groups), default=4) + 2
        ctr_w = max((len(k[1]) for k in groups), default=10) + 2
        pod_w = max(pod_w, 6)
        ctr_w = max(ctr_w, 12)

        header = (
            f"{'Pod':<{pod_w}} {'Container':<{ctr_w}}"
            f" {'CPU avg':>9} {'CPU peak':>9}"
            f" {'Mem avg':>9} {'Mem peak':>9}"
            f" {'Spikes':>7}"
        )
        sep = "─" * len(header)
        rows = [sep, f"[live {window_sec:.0f}s window]", sep, header, sep]

        for (pod, container), s_list in sorted(groups.items()):
            cpus = [s.cpu_millis for s in s_list]
            mems = [s.mem_mib for s in s_list]
            spikes = sum(1 for s in s_list if s.is_spike)
            rows.append(
                f"{pod:<{pod_w}} {container:<{ctr_w}}"
                f" {sum(cpus)/len(cpus):>8.1f}m {max(cpus):>8.1f}m"
                f" {sum(mems)/len(mems):>8.1f}M {max(mems):>8.1f}M"
                f" {spikes:>7}"
            )

        rows.append(sep)
        logger.info("\n" + "\n".join(rows))

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample_once()
            self._stop.wait(self.interval_sec)
