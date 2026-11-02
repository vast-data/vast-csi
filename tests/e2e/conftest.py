"""e2e fixtures: one Kubernetes cluster, one VAST system."""
from __future__ import annotations

from pathlib import Path

import pytest

from e2e.cluster import (
    charts_for_session,
    features_for_session,
    install_csi_driver,
    make_k8s,
)
from lib.constants import BLOCK_SUBSYSTEM, RESOURCE_LIVE_REPORT_EVERY
from lib.k8s.resource_sampler import (
    CSI_RESOURCE_BUDGETS,
    ResourceLimitExceeded,
    ResourceSampler,
)
from e2e.logging import logger, progress, visible
from lib.rest.session import session_from_env


def pytest_addoption(parser):
    parser.addoption("--stress-waves", type=int, default=3)
    parser.addoption("--nfs-stress-pvcs", type=int, default=30)
    parser.addoption("--block-stress-pvcs", type=int, default=20)
    parser.addoption("--stress-io-soak", type=float, default=60.0)


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    setattr(item, "rep_" + call.when, outcome.get_result())


@pytest.fixture(scope="session")
def system(request, pytestconfig):
    """Load the VAST session, ping a VIP, ensure NFS4 exports and the block subsystem."""
    session = session_from_env()
    progress("Pinging a VIP from vippool-1...", pytestconfig)
    session.vippools.verify_vip_connectivity()
    progress(f"Ensuring NFS+NFS4 exports on {session.endpoint}...", pytestconfig)
    session.views.ensure_export(path="/", protocols=["NFS", "NFS4"])
    if any(item.get_closest_marker("nfs") for item in request.session.items):
        progress("Enabling VAST trash folder...", pytestconfig)
        session.clusters.ensure_trash_state(True)
    if any(item.get_closest_marker("block") for item in request.session.items):
        progress(f"Ensuring BLOCK subsystem /{BLOCK_SUBSYSTEM}...", pytestconfig)
        session.views.ensure_subsystem(path=f"/{BLOCK_SUBSYSTEM}", subsystem=BLOCK_SUBSYSTEM)
    progress("VAST datapath is reachable", pytestconfig)
    return session


@pytest.fixture(scope="session")
def cluster(request, system, pytestconfig):
    progress("Installing CSI driver (helm) — first test waits here", pytestconfig)
    k8s = make_k8s()
    charts = charts_for_session(request.session)
    install_csi_driver(
        k8s, system, charts, features=features_for_session(request.session)
    )
    progress("CSI driver is ready", pytestconfig)
    return k8s


_RESOURCE_DRIVER_BY_MARK = {
    "nfs": ("nfs", ("csi-vast-controller", "csi-vast-node"), "csi-vast-plugin"),
    "mtls": ("nfs", ("csi-vast-controller", "csi-vast-node"), "csi-vast-plugin"),
    "block": (
        "block",
        ("block-vast-controller", "block-vast-node"),
        "csi-vast-plugin",
    ),
    "cosi": ("cosi", ("cosi-vast-provisioner",), "cosi-vast-plugin"),
}
_E2E_DIR = Path(__file__).parent


def _resource_spec(node):
    matches = list(
        dict.fromkeys(
            spec
            for mark, spec in _RESOURCE_DRIVER_BY_MARK.items()
            if node.get_closest_marker(mark)
        )
    )
    if not matches:
        raise pytest.UsageError(
            f"{node.nodeid} has no resource-driver marker; "
            "add one of nfs, mtls, block, or cosi"
        )
    if len(matches) != 1:
        raise pytest.UsageError(
            f"{node.nodeid} has ambiguous resource-driver markers: {matches}"
        )
    return matches[0]


def pytest_collection_modifyitems(items):
    """Reject any e2e test that would run without a resource budget."""
    for item in items:
        if item.path.is_relative_to(_E2E_DIR):
            _resource_spec(item)


def _body_ran(node) -> bool:
    """True when the test body executed, so the driver was actually exercised.

    A body that skipped, or never started because another fixture failed,
    puts no load on the driver and leaves nothing for the sampler to see.
    """
    report = getattr(node, "rep_call", None)
    return report is not None and not report.skipped


@pytest.fixture(autouse=True)
def resource_sampler(request, cluster):
    """Enforce the matching driver's hard limits around every e2e test."""
    driver, pod_markers, plugin_container = _resource_spec(request.node)
    budget = CSI_RESOURCE_BUDGETS[driver]
    sampler = ResourceSampler(
        cluster.kubectl,
        budget=budget,
        pod_markers=pod_markers,
    )
    for role, role_budget in (
        ("controller", budget.controller),
        ("node", budget.node),
    ):
        logger.info(
            f"CSI {driver} {role} budget: "
            f"CPU <= {role_budget.cpu_millis:.0f}m, "
            f"memory <= {role_budget.memory_mib:.0f}MiB"
        )
    try:
        with sampler.hard_limits(budget, container=plugin_container):
            sampler.start()
            sampler.start_live_reporting(
                RESOURCE_LIVE_REPORT_EVERY,
                line_writer=lambda msg: visible(msg, request.config),
            )
            try:
                yield sampler
            finally:
                sampler.stop()
                sampler.report(request.node.nodeid)
                if not _body_ran(request.node):
                    sampler.waive_sample_requirement()
    except ResourceLimitExceeded as exc:
        # Every later test would be measuring a driver we already know is over
        # budget, so end the session instead of collecting noise.
        request.session.shouldstop = (
            f"CSI {driver} resource hard limit exceeded in "
            f"{request.node.nodeid}: {exc}"
        )
        raise


@pytest.fixture
def k8s(cluster, request):
    cluster.clear_creation_recordings()
    yield cluster
    failed = getattr(getattr(request.node, "rep_call", None), "failed", False)
    if failed:
        logger.notice("Skipping k8s cleanup after failure (resources preserved for debugging)")
        return
    cluster.cleanup_creation_recordings(parallel=True)
