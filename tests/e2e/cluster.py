"""Single Kubernetes cluster for CSI e2e (the kubeconfig current-context)."""
from __future__ import annotations

import os

from plumbum import local

from lib.builders.helm import FleetHelmValuesBuilder
from lib.constants import CHARTS_DIR, CSI_NAMESPACE, MGMT_SECRET, csi_plugin_image
from e2e.logging import logger
from lib.k8s import K8S, make_k8s as make_k8s_client

_CHART_BY_MARK = {
    "nfs": ["vastcsi"],
    "block": ["vastblock"],
    "cosi": ["vastcosi"],
}


def charts_for_session(session) -> list[str]:
    override = os.environ.get("E2E_CHARTS")
    if override:
        return [c.strip() for c in override.split(",") if c.strip()]
    charts: list[str] = []
    seen: set[str] = set()
    for item in session.items:
        for mark, names in _CHART_BY_MARK.items():
            if item.get_closest_marker(mark):
                for name in names:
                    if name not in seen:
                        seen.add(name)
                        charts.append(name)
    return charts or ["vastcsi"]


_SNAPSHOT_PREREQ_HINT = "Install them with: make install-snapshost-crds"
_COSI_PREREQ_HINT = "Install them with: make install-cosi-crds"


def _require_snapshot_prereqs(kube_cmd) -> None:
    """Fail before helm if snapshot CRDs / controller are missing. Tests never install them."""
    rc, _, _ = kube_cmd["get", "crd", "volumesnapshots.snapshot.storage.k8s.io"].run(retcode=None)
    if rc != 0:
        raise RuntimeError(
            f"Snapshot CRDs are not installed on this cluster. {_SNAPSHOT_PREREQ_HINT}"
        )

    rc, stdout, _ = kube_cmd["get", "deploy", "-A", "-o", "name"].run(retcode=None)
    if rc != 0 or "snapshot-controller" not in (stdout or ""):
        raise RuntimeError(
            "Snapshot CRDs are installed, but snapshot-controller is not. "
            f"VolumeSnapshots will not reconcile until the controller is running. {_SNAPSHOT_PREREQ_HINT}"
        )
    logger.info("Snapshot CRDs and snapshot-controller are present.")


def _require_cosi_prereqs(kube_cmd) -> None:
    """Fail before helm if COSI CRDs / controller are missing. Tests never install them."""
    rc, _, _ = kube_cmd["get", "crd", "bucketclaims.objectstorage.k8s.io"].run(retcode=None)
    if rc != 0:
        raise RuntimeError(
            f"COSI CRDs are not installed on this cluster. {_COSI_PREREQ_HINT}"
        )

    rc, stdout, _ = kube_cmd["get", "deploy", "-A", "-o", "name"].run(retcode=None)
    if rc != 0 or "objectstorage-controller" not in (stdout or ""):
        raise RuntimeError(
            "COSI CRDs are installed, but objectstorage-controller is not. "
            f"BucketClaims will not reconcile until the controller is running. {_COSI_PREREQ_HINT}"
        )
    logger.info("COSI CRDs and objectstorage-controller are present.")


def install_csi_driver(k8s: K8S, system, charts: list[str]) -> None:
    """helm upgrade --install charts/<chart> -f <generated overlay> -n default."""
    if any(chart in ("vastcsi", "vastblock") for chart in charts):
        _require_snapshot_prereqs(k8s.kubectl)
    if "vastcosi" in charts:
        _require_cosi_prereqs(k8s.kubectl)
    k8s.namespaces.allow_privileged(CSI_NAMESPACE)
    image = csi_plugin_image()
    logger.info(f"CSI plugin image: {image or '(chart default)'}")
    k8s.secrets.ensure(
        name=MGMT_SECRET,
        namespace=CSI_NAMESPACE,
        username=system.username,
        password=system.password,
        endpoint=system.endpoint,
    )

    builder = FleetHelmValuesBuilder.for_fleet(
        system,
        csi_image=csi_plugin_image(),
    )

    k8s.helmvalues.install(
        charts_dir=local.path(str(CHARTS_DIR)),
        namespace=CSI_NAMESPACE,
        subst_values_by_chart=builder.result_by_chart(),
        charts=charts,
    )


def _check_cluster_reachable(kube_cmd) -> None:
    """Fail fast with a clear message when the Kubernetes API server is unreachable."""
    rc, _, stderr = kube_cmd["get", "nodes"].run(retcode=None)
    if rc != 0:
        context = local["kubectl"]["config", "current-context"].run(retcode=None)[1].strip()
        raise RuntimeError(
            f"Kubernetes cluster is not reachable (context: {context!r}).\n"
            f"Details: {stderr.strip()}"
        )


def make_k8s() -> K8S:
    k8s = make_k8s_client(helm=True)
    _check_cluster_reachable(k8s.kubectl)
    return k8s

