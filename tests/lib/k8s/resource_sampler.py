"""Background CPU and memory sampler for CSI pod containers."""
from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Callable, Iterator, NamedTuple

from lib.constants import (
    CPU_MAX_BLOCK_CONTROLLER,
    CPU_MAX_BLOCK_NODE,
    CPU_MAX_COSI_CONTROLLER,
    CPU_MAX_NFS_CONTROLLER,
    CPU_MAX_NFS_NODE,
    CSI_NAMESPACE,
    MEM_MAX_BLOCK_CONTROLLER,
    MEM_MAX_BLOCK_NODE,
    MEM_MAX_COSI_CONTROLLER,
    MEM_MAX_NFS_CONTROLLER,
    MEM_MAX_NFS_NODE,
)
from lib.logging import logger

_CPU_METRIC = "container_cpu_usage_seconds_total"
_MEM_METRIC = "container_memory_working_set_bytes"
_METRIC_LINE_RE = re.compile(
    r'^([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([\d.eE+\-]+)'
)
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')
_CSI_POD_MARKERS = (
    "csi-vast-node",
    "csi-vast-controller",
    "block-vast-node",
    "block-vast-controller",
)


class _Sample(NamedTuple):
    ts: float
    pod: str
    container: str
    cpu_millis: float
    mem_mib: float
    is_spike: bool


@dataclass(frozen=True)
class ResourceBudget:
    """Fixed ceilings one plugin container must stay within."""

    cpu_millis: float
    memory_mib: float


@dataclass(frozen=True)
class DriverBudget:
    """Controller and node are sized differently, so they are judged separately."""

    controller: ResourceBudget
    node: ResourceBudget

    def for_pod(self, pod: str) -> ResourceBudget:
        return self.controller if "controller" in pod else self.node


CSI_RESOURCE_BUDGETS: dict[str, DriverBudget] = {
    "nfs": DriverBudget(
        controller=ResourceBudget(CPU_MAX_NFS_CONTROLLER, MEM_MAX_NFS_CONTROLLER),
        node=ResourceBudget(CPU_MAX_NFS_NODE, MEM_MAX_NFS_NODE),
    ),
    "block": DriverBudget(
        controller=ResourceBudget(CPU_MAX_BLOCK_CONTROLLER, MEM_MAX_BLOCK_CONTROLLER),
        node=ResourceBudget(CPU_MAX_BLOCK_NODE, MEM_MAX_BLOCK_NODE),
    ),
    "cosi": DriverBudget(
        controller=ResourceBudget(CPU_MAX_COSI_CONTROLLER, MEM_MAX_COSI_CONTROLLER),
        node=ResourceBudget(CPU_MAX_COSI_CONTROLLER, MEM_MAX_COSI_CONTROLLER),
    ),
}


@dataclass(frozen=True)
class _HardLimits:
    budget: DriverBudget
    container: str
    started_at: float
    require_samples: bool
    fail_on_restart: bool
    initial_restarts: dict[str, int]


class ResourceLimitExceeded(AssertionError):
    """A CSI container exceeded a configured test resource limit."""


@dataclass
class ResourceSampler:
    """Sample CSI container CPU/memory from every kubelet cAdvisor endpoint."""

    kubectl: object
    namespace: str = CSI_NAMESPACE
    interval_sec: float = 1.0
    budget: DriverBudget | None = None
    pod_markers: tuple[str, ...] = _CSI_POD_MARKERS
    # When set (e2e: pytest terminalreporter), mem/CPU tables bypass capture
    # without enabling -s / --log-cli-level for the whole process.
    line_writer: Callable[[str], None] | None = None

    _samples: list[_Sample] = field(default_factory=list, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _live_thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _live_interval_sec: float | None = field(default=None, init=False, repr=False)
    _node_names: list[str] = field(default_factory=list, init=False, repr=False)
    _prev_cpu: dict[tuple[str, str], tuple[float, float]] = field(
        default_factory=dict, init=False, repr=False
    )
    _initial_restarts: dict[str, int] = field(default_factory=dict, init=False, repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _active_limits: _HardLimits | None = field(default=None, init=False, repr=False)
    _limit_violations: list[str] = field(default_factory=list, init=False, repr=False)
    _sampling_errors: list[str] = field(default_factory=list, init=False, repr=False)
    # First-seen working-set MiB per (pod, container); Δ is growth since then.
    _baseline_mem: dict[tuple[str, str], float] = field(
        default_factory=dict, init=False, repr=False
    )
    _plugin_container: str = field(default="csi-vast-plugin", init=False, repr=False)

    def start(self) -> None:
        self._stop.clear()
        self._samples.clear()
        self._prev_cpu.clear()
        self._limit_violations.clear()
        self._sampling_errors.clear()
        self._baseline_mem.clear()
        self._node_names = self._discover_nodes()
        if not self._node_names:
            logger.warning("ResourceSampler: no Kubernetes nodes found; sampling disabled")
            return
        self._initial_restarts = self._get_restart_counts()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="resource-sampler"
        )
        self._thread.start()

    def start_live_reporting(
        self,
        interval_sec: float = 10.0,
        *,
        line_writer: Callable[[str], None] | None = None,
    ) -> None:
        """Report resource use for each recent window while the test is running.

        By default rows go to the logger (hidden under pytest capture unless
        ``-s`` / ``--log-cli-level``). Pass ``line_writer`` to also (or instead)
        print always-visible terminal lines — intended for long load runs.
        """
        self._live_interval_sec = interval_sec
        if line_writer is not None:
            self.line_writer = line_writer
            # Confirm from the caller thread immediately; the first table only
            # appears after ``interval_sec`` (and only if samples exist).
            line_writer(
                f"ResourceSampler: live CPU/mem every {interval_sec:.0f}s "
                f"(nodes={len(self._node_names) or 'none'})"
            )
        if self._thread is not None and self._live_thread is None:
            self._live_thread = threading.Thread(
                target=self._live_report_loop,
                daemon=True,
                name="resource-sampler-live",
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
        """Log pod/plugin memory since start (leak signal) and restart deltas."""
        if not self._samples:
            msg = f"ResourceSampler: no samples collected for {test_name!r}"
            if self.line_writer is not None:
                self.line_writer(msg)
            else:
                logger.info(msg)
            return
        self._log_samples(
            self._samples,
            f"mem leak check — {test_name}" if test_name else "mem leak check",
            include_restarts=True,
        )

    @contextmanager
    def hard_limits(
        self,
        budget: DriverBudget,
        *,
        container: str = "csi-vast-plugin",
        require_samples: bool = True,
        fail_on_restart: bool = True,
    ) -> Iterator["ResourceSampler"]:
        """Fail if any matching container breaches the budget.

        Applies to every matching controller and node container. A single
        sample over a ceiling is sufficient to fail; values are not averaged.
        """
        if self._active_limits is not None:
            raise RuntimeError("ResourceSampler hard-limit contexts cannot be nested")

        limits = _HardLimits(
            budget=budget,
            container=container,
            started_at=time.monotonic(),
            require_samples=require_samples,
            fail_on_restart=fail_on_restart,
            # Sidecar restarts (e.g. csi-provisioner racing the plugin socket
            # on a fresh cluster) are ignored; only the driver container counts.
            initial_restarts=self._get_restart_counts(container=container),
        )
        with self._lock:
            self._plugin_container = container
            self._active_limits = limits
            self._limit_violations.clear()
        try:
            yield self
            self.raise_if_limits_exceeded()
            with self._lock:
                # Re-read: the body may have waived the sample requirement.
                limits = self._active_limits
            self._assert_limit_context_complete(limits)
        finally:
            with self._lock:
                self._active_limits = None

    def waive_sample_requirement(self) -> None:
        """Accept an empty sample set for the active hard-limit context.

        Silence only means a blind spot when the workload actually ran; a body
        that skipped or never started leaves cAdvisor nothing to report.
        """
        with self._lock:
            if self._active_limits is not None:
                self._active_limits = replace(
                    self._active_limits, require_samples=False
                )

    def raise_if_limits_exceeded(self) -> None:
        """Raise immediately when the active hard-limit context has a violation."""
        with self._lock:
            violations = list(self._limit_violations)
            errors = list(self._sampling_errors)
        if violations:
            raise ResourceLimitExceeded(
                "CSI resource hard limit exceeded:\n" + "\n".join(violations)
            )
        if errors:
            raise ResourceLimitExceeded(
                "Resource sampling failed while hard limits were active:\n"
                + "\n".join(errors)
            )

    def _discover_nodes(self) -> list[str]:
        try:
            raw = self.kubectl("get", "nodes", "-o", "json")
            return [
                item["metadata"]["name"]
                for item in json.loads(raw).get("items", [])
            ]
        except Exception as exc:
            logger.warning(f"ResourceSampler: node discovery failed: {exc}")
            return []

    def _fetch_cadvisor(self, node_name: str) -> str:
        return self.kubectl(
            "get", "--raw", f"/api/v1/nodes/{node_name}/proxy/metrics/cadvisor"
        )

    def _parse_cadvisor(
        self, text: str
    ) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
        cpu_counters: dict[tuple[str, str], float] = {}
        mem_gauges: dict[tuple[str, str], float] = {}
        for line in text.splitlines():
            match = _METRIC_LINE_RE.match(line)
            if not match or match.group(1) not in (_CPU_METRIC, _MEM_METRIC):
                continue
            labels = dict(_LABEL_RE.findall(match.group(2)))
            if labels.get("namespace") != self.namespace:
                continue
            pod = labels.get("pod", "")
            container = labels.get("container", "")
            if (
                not pod
                or not container
                or not any(marker in pod for marker in self.pod_markers)
            ):
                continue
            try:
                value = float(match.group(3))
            except ValueError:
                continue
            key = (pod, container)
            if match.group(1) == _CPU_METRIC:
                cpu_counters[key] = max(cpu_counters.get(key, 0.0), value)
            else:
                mem_gauges[key] = max(mem_gauges.get(key, 0.0), value)
        return cpu_counters, mem_gauges

    def _sample_once(self) -> None:
        now = time.monotonic()
        cpu_counters: dict[tuple[str, str], float] = {}
        mem_gauges: dict[tuple[str, str], float] = {}
        for node_name in self._node_names:
            try:
                node_cpu, node_mem = self._parse_cadvisor(
                    self._fetch_cadvisor(node_name)
                )
            except Exception as exc:
                logger.debug(
                    f"ResourceSampler: cAdvisor fetch failed for {node_name!r}: {exc}"
                )
                with self._lock:
                    if self._active_limits is not None:
                        self._sampling_errors.append(
                            f"cAdvisor fetch failed for {node_name!r}: {exc}"
                        )
                continue
            for key, value in node_cpu.items():
                cpu_counters[key] = max(cpu_counters.get(key, 0.0), value)
            for key, value in node_mem.items():
                mem_gauges[key] = max(mem_gauges.get(key, 0.0), value)

        for key, cpu_counter in cpu_counters.items():
            previous = self._prev_cpu.get(key)
            mem_mib = mem_gauges.get(key, 0.0) / (1024 * 1024)
            if previous is None or cpu_counter < previous[1]:
                self._prev_cpu[key] = (now, cpu_counter)
                cpu_millis = 0.0
            elif cpu_counter == previous[1]:
                # Keep tracking memory even when an idle container's CPU
                # counter has not advanced.
                cpu_millis = 0.0
            else:
                elapsed = now - previous[0]
                if elapsed <= 0:
                    continue
                cpu_millis = max(
                    0.0, (cpu_counter - previous[1]) / elapsed * 1000.0
                )
                self._prev_cpu[key] = (now, cpu_counter)

            self._record_sample(
                _Sample(
                    ts=now,
                    pod=key[0],
                    container=key[1],
                    cpu_millis=cpu_millis,
                    mem_mib=mem_mib,
                    is_spike=self.budget is not None
                    and (
                        cpu_millis > self.budget.for_pod(key[0]).cpu_millis
                        or mem_mib > self.budget.for_pod(key[0]).memory_mib
                    ),
                )
            )

    def _record_sample(self, sample: _Sample) -> None:
        with self._lock:
            key = (sample.pod, sample.container)
            if key not in self._baseline_mem:
                self._baseline_mem[key] = sample.mem_mib
            self._samples.append(sample)
            limits = self._active_limits
            if limits is None or sample.container != limits.container:
                return
            budget = limits.budget.for_pod(sample.pod)
            if sample.cpu_millis > budget.cpu_millis:
                self._limit_violations.append(
                    f"{sample.pod}/{sample.container}: CPU "
                    f"{sample.cpu_millis:.1f}m > {budget.cpu_millis:.1f}m"
                )
            if sample.mem_mib > budget.memory_mib:
                self._limit_violations.append(
                    f"{sample.pod}/{sample.container}: memory "
                    f"{sample.mem_mib:.1f}MiB > {budget.memory_mib:.1f}MiB"
                )

    def _assert_limit_context_complete(self, limits: _HardLimits) -> None:
        with self._lock:
            matching_samples = [
                sample
                for sample in self._samples
                if sample.ts >= limits.started_at
                and sample.container == limits.container
            ]
        if limits.require_samples and not matching_samples:
            raise ResourceLimitExceeded(
                f"No resource samples collected for container {limits.container!r}; "
                "hard limits cannot be verified"
            )
        if not limits.fail_on_restart:
            return
        final_restarts = self._get_restart_counts(container=limits.container)
        restarted = {
            pod: final_restarts.get(pod, 0) - limits.initial_restarts.get(pod, 0)
            for pod in set(final_restarts) | set(limits.initial_restarts)
            if final_restarts.get(pod, 0) - limits.initial_restarts.get(pod, 0) > 0
        }
        if restarted:
            details = ", ".join(
                f"{pod}=+{count}" for pod, count in sorted(restarted.items())
            )
            raise ResourceLimitExceeded(
                f"CSI container {limits.container!r} restarted while hard limits "
                f"were active: {details}"
            )

    def _get_restart_counts(self, *, container: str | None = None) -> dict[str, int]:
        """Return per-pod restart counts for CSI pods.

        When ``container`` is set (or hard limits are active), only that
        container's ``restartCount`` is counted — sidecars are ignored.
        """
        target = container
        if target is None and self._active_limits is not None:
            target = self._active_limits.container
        if target is None:
            target = "csi-vast-plugin"
        try:
            raw = self.kubectl(
                "get", "pods", "-n", self.namespace, "-o", "json"
            )
            counts: dict[str, int] = {}
            for pod in json.loads(raw).get("items", []):
                name = pod["metadata"]["name"]
                if not any(marker in name for marker in self.pod_markers):
                    continue
                counts[name] = sum(
                    status.get("restartCount", 0)
                    for status in pod.get("status", {}).get("containerStatuses", [])
                    if status.get("name") == target
                )
            return counts
        except Exception:
            return {}

    def _live_report_loop(self) -> None:
        while not self._stop.wait(self._live_interval_sec):
            cutoff = time.monotonic() - self._live_interval_sec
            with self._lock:
                samples = [sample for sample in self._samples if sample.ts >= cutoff]
                errors = list(self._sampling_errors[-3:])
            if samples:
                self._log_samples(
                    samples,
                    f"mem leak check — last {self._live_interval_sec:.0f}s "
                    f"(Δ since run start)",
                )
            elif self.line_writer is not None:
                detail = (
                    f"; recent errors: {'; '.join(errors)}"
                    if errors
                    else ""
                )
                self.line_writer(
                    f"ResourceSampler: no samples in last "
                    f"{self._live_interval_sec:.0f}s "
                    f"(nodes={len(self._node_names) or 'none'}){detail}"
                )

    def _log_samples(
        self,
        samples: list[_Sample],
        title: str,
        *,
        include_restarts: bool = False,
    ) -> None:
        """Slim mem report: pod total (eviction) + plugin (our process leak)."""
        latest: dict[tuple[str, str], _Sample] = {}
        for sample in samples:
            latest[(sample.pod, sample.container)] = sample

        by_pod: dict[str, dict[str, _Sample]] = defaultdict(dict)
        for (pod, container), sample in latest.items():
            by_pod[pod][container] = sample

        with self._lock:
            baselines = dict(self._baseline_mem)
            plugin = self._plugin_container

        rows = [title]
        for pod in sorted(by_pod):
            containers = by_pod[pod]
            pod_now = sum(s.mem_mib for s in containers.values())
            pod_base = sum(
                baselines.get((pod, name), s.mem_mib)
                for name, s in containers.items()
            )
            plugin_sample = containers.get(plugin)
            if plugin_sample is not None:
                plugin_now = plugin_sample.mem_mib
                plugin_base = baselines.get((pod, plugin), plugin_now)
                plugin_part = (
                    f"  plugin={plugin_now:.1f}M (Δ{plugin_now - plugin_base:+.1f}M)"
                )
            else:
                plugin_part = f"  plugin={plugin!r}:n/a"
            rows.append(
                f"{pod}  pod={pod_now:.1f}M (Δ{pod_now - pod_base:+.1f}M)"
                f"{plugin_part}"
            )

        if include_restarts:
            final = self._get_restart_counts()
            deltas = {
                pod: final.get(pod, 0) - self._initial_restarts.get(pod, 0)
                for pod in set(final) | set(self._initial_restarts)
            }
            restarted = {pod: count for pod, count in deltas.items() if count > 0}
            rows.append(
                "Restarts: "
                + (
                    ", ".join(f"{pod}=+{count}" for pod, count in sorted(restarted.items()))
                    if restarted
                    else "none"
                )
            )
        text = "\n".join(rows)
        if self.line_writer is not None:
            self.line_writer(text)
        else:
            logger.info("\n" + text)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._sample_once()
            except Exception as exc:
                message = f"sampler loop failed: {type(exc).__name__}: {exc}"
                logger.error(f"ResourceSampler: {message}")
                with self._lock:
                    self._sampling_errors.append(message)
            self._stop.wait(self.interval_sec)
