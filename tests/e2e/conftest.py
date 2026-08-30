"""e2e fixtures: one Kubernetes cluster, one VAST system."""
from __future__ import annotations

import pytest

from e2e.cluster import (
    charts_for_session,
    features_for_session,
    install_csi_driver,
    make_k8s,
)
from lib.constants import BLOCK_SUBSYSTEM
from e2e.logging import logger, progress
from lib.rest.session import session_from_env


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


@pytest.fixture
def k8s(cluster, request):
    cluster.clear_creation_recordings()
    yield cluster
    failed = getattr(getattr(request.node, "rep_call", None), "failed", False)
    if failed:
        logger.notice("Skipping k8s cleanup after failure (resources preserved for debugging)")
        return
    cluster.cleanup_creation_recordings(parallel=True)
