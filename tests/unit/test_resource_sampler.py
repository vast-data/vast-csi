import time

import pytest

import yaml

from lib.constants import REPO_ROOT
from lib.k8s.resource_sampler import (
    CSI_RESOURCE_BUDGETS,
    DriverBudget,
    ResourceBudget,
    ResourceLimitExceeded,
    ResourceSampler,
    _Sample,
)

BUDGET = DriverBudget(
    controller=ResourceBudget(cpu_millis=100.0, memory_mib=80.0),
    node=ResourceBudget(cpu_millis=200.0, memory_mib=100.0),
)


CADVISOR = """
container_cpu_usage_seconds_total{namespace="default",pod="csi-vast-node-abc",container="csi-vast-plugin"} 10
container_memory_working_set_bytes{namespace="default",pod="csi-vast-node-abc",container="csi-vast-plugin"} 104857600
container_cpu_usage_seconds_total{namespace="default",pod="unrelated",container="app"} 20
container_memory_working_set_bytes{namespace="other",pod="csi-vast-node-other",container="csi-vast-plugin"} 1
"""


def test_parse_cadvisor_keeps_only_csi_containers():
    sampler = ResourceSampler(kubectl=None)

    cpu, memory = sampler._parse_cadvisor(CADVISOR)

    key = ("csi-vast-node-abc", "csi-vast-plugin")
    assert cpu == {key: 10.0}
    assert memory == {key: 104857600.0}


def test_parse_cadvisor_can_target_cosi_plugin():
    sampler = ResourceSampler(
        kubectl=None,
        pod_markers=("cosi-vast-provisioner",),
    )
    metrics = """
container_cpu_usage_seconds_total{namespace="default",pod="cosi-vast-provisioner-abc",container="cosi-vast-plugin"} 4
container_memory_working_set_bytes{namespace="default",pod="cosi-vast-provisioner-abc",container="cosi-vast-plugin"} 52428800
container_memory_working_set_bytes{namespace="default",pod="csi-vast-controller-abc",container="csi-vast-plugin"} 104857600
"""

    cpu, memory = sampler._parse_cadvisor(metrics)

    key = ("cosi-vast-provisioner-abc", "cosi-vast-plugin")
    assert cpu == {key: 4.0}
    assert memory == {key: 52428800.0}


def test_cpu_is_calculated_from_counter_delta(monkeypatch):
    sampler = ResourceSampler(kubectl=None)
    sampler._node_names = ["worker-1"]
    samples = iter(
        [
            CADVISOR,
            CADVISOR.replace("} 10\n", "} 10.5\n", 1),
        ]
    )
    monkeypatch.setattr(sampler, "_fetch_cadvisor", lambda _node: next(samples))
    times = iter([100.0, 101.0])
    monkeypatch.setattr(
        "lib.k8s.resource_sampler.time.monotonic", lambda: next(times)
    )

    sampler._sample_once()
    sampler._sample_once()

    assert len(sampler._samples) == 2
    assert sampler._samples[0].cpu_millis == 0.0
    sample = sampler._samples[1]
    assert sample.cpu_millis == pytest.approx(500.0)
    assert sample.mem_mib == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("cpu_millis", "memory_mib", "message"),
    [
        (200.1, 50.0, "CPU"),
        (50.0, 100.1, "memory"),
    ],
)
def test_hard_limit_context_rejects_single_sample_breach(
    cpu_millis, memory_mib, message
):
    sampler = ResourceSampler(kubectl=None)

    with pytest.raises(ResourceLimitExceeded, match=message):
        with sampler.hard_limits(BUDGET, fail_on_restart=False):
            sampler._record_sample(
                _Sample(
                    time.monotonic(),
                    "node-pod",
                    "csi-vast-plugin",
                    cpu_millis,
                    memory_mib,
                    False,
                )
            )


def _millis(cpu: str) -> float:
    return float(cpu[:-1]) if cpu.endswith("m") else float(cpu) * 1000


def _mib(memory: str) -> float:
    return float(memory.removesuffix("Mi"))


@pytest.mark.parametrize(
    ("driver", "chart"), [("nfs", "vastcsi"), ("block", "vastblock")]
)
def test_budgets_stay_tethered_to_the_chart(driver, chart):
    """Budgets must track what the chart sizes the plugin for.

    The charts declare no CPU limit, so requests.cpu is the only number the
    driver is nominally sized for; allowing multiples of it tests nothing. The
    500Mi memory limit is the OOM-kill point, so a budget anywhere near it only
    fires once the driver is already dying.
    """
    values = yaml.safe_load((REPO_ROOT / "charts" / chart / "values.yaml").read_text())
    budget = CSI_RESOURCE_BUDGETS[driver]

    for role in ("controller", "node"):
        declared = values[role]["resources"]["csiVastPlugin"]
        role_budget = getattr(budget, role)
        assert role_budget.cpu_millis <= 2 * _millis(declared["requests"]["cpu"])
        assert role_budget.memory_mib <= 0.4 * _mib(declared["limits"]["memory"])


def test_cosi_budget_stays_tethered_to_the_chart():
    values = yaml.safe_load(
        (REPO_ROOT / "charts" / "vastcosi" / "values.yaml").read_text()
    )
    declared = values["cosiplugin"]["resources"]["cosiVastPlugin"]
    budget = CSI_RESOURCE_BUDGETS["cosi"].controller

    assert budget.cpu_millis <= _millis(declared["requests"]["cpu"])
    assert budget.memory_mib <= 0.4 * _mib(declared["limits"]["memory"])


def test_budgets_stay_close_to_measured_usage():
    """Measured peaks under NFSv4 churn: 49.8MiB controller, 64.8MiB node."""
    assert set(CSI_RESOURCE_BUDGETS) == {"nfs", "block", "cosi"}
    for budget in CSI_RESOURCE_BUDGETS.values():
        assert 49.8 < budget.controller.memory_mib <= 100
        assert 64.8 < budget.node.memory_mib <= 150


def test_hard_limit_context_fails_when_no_samples_exist():
    sampler = ResourceSampler(kubectl=None)

    with pytest.raises(ResourceLimitExceeded, match="No resource samples"):
        with sampler.hard_limits(BUDGET, fail_on_restart=False):
            pass


def test_waived_sample_requirement_tolerates_an_empty_sample_set():
    """A skipped body drives no load, so silence must not fail the test."""
    sampler = ResourceSampler(kubectl=None)

    with sampler.hard_limits(BUDGET, fail_on_restart=False):
        sampler.waive_sample_requirement()


def test_waiver_still_reports_a_breach_that_was_already_recorded():
    sampler = ResourceSampler(kubectl=None)

    with pytest.raises(ResourceLimitExceeded, match="memory"):
        with sampler.hard_limits(BUDGET, fail_on_restart=False):
            sampler._record_sample(
                _Sample(
                    time.monotonic(),
                    "csi-vast-controller-abc",
                    "csi-vast-plugin",
                    10.0,
                    500.0,
                    False,
                )
            )
            sampler.waive_sample_requirement()


def test_controller_and_node_are_judged_against_their_own_ceilings():
    """90MiB is fine on the node (100MiB) and a failure on the controller (80MiB)."""
    sampler = ResourceSampler(kubectl=None)

    with pytest.raises(ResourceLimitExceeded, match="90.0MiB > 80.0MiB"):
        with sampler.hard_limits(BUDGET, fail_on_restart=False):
            sampler._record_sample(
                _Sample(
                    time.monotonic(),
                    "csi-vast-node-abc",
                    "csi-vast-plugin",
                    10.0,
                    90.0,
                    False,
                )
            )
            sampler.raise_if_limits_exceeded()

            sampler._record_sample(
                _Sample(
                    time.monotonic(),
                    "csi-vast-controller-abc",
                    "csi-vast-plugin",
                    10.0,
                    90.0,
                    False,
                )
            )


def test_restart_counts_ignore_sidecar_containers():
    """csi-provisioner (etc.) may crash once waiting for the plugin socket."""
    pod_list = {
        "items": [
            {
                "metadata": {"name": "block-vast-controller-abc"},
                "status": {
                    "containerStatuses": [
                        {"name": "csi-provisioner", "restartCount": 2},
                        {"name": "csi-attacher", "restartCount": 1},
                        {"name": "csi-vast-plugin", "restartCount": 0},
                    ]
                },
            },
            {
                "metadata": {"name": "block-vast-node-xyz"},
                "status": {
                    "containerStatuses": [
                        {"name": "csi-node-driver-registrar", "restartCount": 3},
                        {"name": "csi-vast-plugin", "restartCount": 1},
                    ]
                },
            },
            {
                "metadata": {"name": "unrelated-pod"},
                "status": {
                    "containerStatuses": [
                        {"name": "csi-vast-plugin", "restartCount": 9},
                    ]
                },
            },
        ]
    }

    class _FakeKubectl:
        def __call__(self, *args, **kwargs):
            import json

            return json.dumps(pod_list)

    sampler = ResourceSampler(
        kubectl=_FakeKubectl(),
        pod_markers=("block-vast-controller", "block-vast-node"),
    )

    assert sampler._get_restart_counts(container="csi-vast-plugin") == {
        "block-vast-controller-abc": 0,
        "block-vast-node-xyz": 1,
    }


def test_hard_limits_ignore_sidecar_restart_but_fail_on_plugin(monkeypatch):
    sampler = ResourceSampler(
        kubectl=None,
        pod_markers=("block-vast-controller",),
    )
    # initial snapshot (hard_limits enter) then final (exit): plugin unchanged
    plugin_counts = iter(
        [
            {"block-vast-controller-abc": 0},
            {"block-vast-controller-abc": 0},
        ]
    )
    monkeypatch.setattr(
        sampler,
        "_get_restart_counts",
        lambda *, container=None: next(plugin_counts),
    )

    with sampler.hard_limits(BUDGET, require_samples=False):
        pass

    # plugin restarted between enter and exit
    plugin_counts_fail = iter(
        [
            {"block-vast-controller-abc": 0},
            {"block-vast-controller-abc": 1},
        ]
    )
    monkeypatch.setattr(
        sampler,
        "_get_restart_counts",
        lambda *, container=None: next(plugin_counts_fail),
    )
    with pytest.raises(ResourceLimitExceeded, match="csi-vast-plugin"):
        with sampler.hard_limits(BUDGET, require_samples=False):
            pass
