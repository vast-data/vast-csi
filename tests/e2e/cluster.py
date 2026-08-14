"""Single Kubernetes cluster for CSI e2e (the kubeconfig current-context)."""
from __future__ import annotations

import os
import shutil

from plumbum import local

from e2e.builders.helm import FleetHelmValuesBuilder
from e2e.constants import CHARTS_DIR, CSI_NAMESPACE, MGMT_SECRET, csi_plugin_image
from e2e.k8s import K8S
from e2e.logging import logger

_CHART_BY_MARK = {
    "nfs": ["vastcsi"],
    "block": ["vastblock"],
    "cosi": ["vastcosi"],
}


def _kube_cmd():
    exe = os.environ.get("E2E_KUBECTL") or (shutil.which("oc") and "oc") or "kubectl"
    cmd = local[exe]
    kubeconfig = os.environ.get("KUBECONFIG")
    if kubeconfig:
        cmd = cmd.with_env(KUBECONFIG=kubeconfig)
    return cmd


def _helm_cmd():
    helm = shutil.which("helm")
    if not helm:
        raise RuntimeError("helm is required to install CSI e2e charts")
    cmd = local[helm]
    kubeconfig = os.environ.get("KUBECONFIG")
    if kubeconfig:
        cmd = cmd.with_env(KUBECONFIG=kubeconfig)
    return cmd


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


def install_csi_driver(k8s: K8S, system, charts: list[str]) -> None:
    """helm upgrade --install charts/<chart> -f <generated overlay> -n default."""
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


def make_k8s() -> K8S:
    return K8S(kube_cmd=_kube_cmd(), helm_cmd=_helm_cmd())
