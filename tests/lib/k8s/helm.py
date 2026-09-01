from __future__ import annotations

from typing import List

import yaml
from easypy.units import MINUTE
from plumbum import FG, local

from lib.constants import CHARTS_DIR, CSI_NAMESPACE
from lib.k8s._base import KubernetesResource
from lib.logging import logger


_VAST_HELM_REPO_NAME = "vast"
_VAST_HELM_REPO_URL = "https://vast-data.github.io/vast-csi"

_CHART_POD_LABELS = {
    "vastcsi":   (["csi-vast-controller", "csi-vast-node"], "nfs"),
    "vastblock": (["csi-vast-controller", "csi-vast-node"], "block"),
    "vastcosi":  (["cosi-provisioner"],                     "cosi"),
}


class HelmValues(KubernetesResource):
    resource_type = "helmvalues"

    def __init__(self, k8s):
        super().__init__(k8s)
        self.installed_charts: dict[str, "HelmValues.Chart"] = {}

    class Chart:
        def __init__(
            self,
            k8s,
            name: str,
            namespace: str,
            chart_dir: local.path,
            values: dict,
            condition_running_labels: List[str],
        ):
            self.k8s = k8s
            self.name = name
            self.namespace = namespace
            self.chart_dir = chart_dir
            self.memoized_values = dict(values)
            self.condition_running_labels = condition_running_labels

        def install(self):
            logger.info(f"helm dependency build --skip-refresh {self.chart_dir}")
            dependency_cmd = self.k8s.helm[
                "dependency", "build", "--skip-refresh", str(self.chart_dir),
            ]
            rc, stdout, stderr = dependency_cmd.run(retcode=None)
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, flush=True)
            if rc != 0:
                output = (stdout + "\n" + stderr).strip()
                raise RuntimeError(
                    f"helm dependency build for chart {self.name!r} failed (exit {rc}).\n"
                    f"Command: helm dependency build --skip-refresh {self.chart_dir}\n"
                    f"Output:\n{output}"
                )

            overlay = self.k8s._next_object_yaml_path(self.k8s.helmvalues.resource_type)
            overlay.write(yaml.safe_dump(self.memoized_values, sort_keys=False))
            logger.info(f"helm upgrade --install {self.name} {self.chart_dir} -n {self.namespace}")
            cmd = self.k8s.helm[
                "upgrade", "--install", self.name,
                str(self.chart_dir), "-f", str(overlay),
                "-n", self.namespace,
            ]
            rc, stdout, stderr = cmd.run(retcode=None)
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, flush=True)
            if rc != 0:
                output = (stdout + "\n" + stderr).strip()
                raise RuntimeError(
                    f"helm install of chart {self.name!r} failed (exit {rc}).\n"
                    f"Command: helm upgrade --install {self.name} {self.chart_dir} -n {self.namespace}\n"
                    f"Output:\n{output}"
                )

        def wait(self):
            for label in self.condition_running_labels:
                logger.info(f"Waiting for {self.name} pod app={label} (up to 5 min)")
                self.k8s.pods.wait(
                    timeout=5 * MINUTE,
                    namespace=self.namespace,
                    labels={"app": label},
                    condition="Running",
                    error_msg=f"Pod with label {label} is not running",
                )
            logger.info(f"{self.name} pods are running")

        def upgrade(self, subst_values: dict):
            if all(self.memoized_values.get(k) == v for k, v in subst_values.items()):
                logger.info(f"Chart {self.name!r}: values unchanged, upgrade skipped.")
                return
            logger.info(f"Chart {self.name!r}: values changed, upgrading.")
            self.memoized_values.update(subst_values)
            self.delete()
            self.install()
            self.wait()

        def delete(self):
            self.k8s.helm[
                "uninstall", self.name, "-n", self.namespace
            ] & FG

    def install(
        self,
        charts_dir=None,
        namespace: str = CSI_NAMESPACE,
        subst_values: dict | None = None,
        *,
        subst_values_by_chart: dict[str, dict] | None = None,
        charts: list[str] | None = None,
    ):
        self._ensure_chart_repo()
        path_to_charts = local.path(str(charts_dir or CHARTS_DIR))
        chart_names = charts or list(_CHART_POD_LABELS)
        for chart_name in chart_names:
            running_labels, _ = _CHART_POD_LABELS[chart_name]
            chart_dir = path_to_charts / chart_name
            if not (chart_dir / "Chart.yaml").exists():
                logger.info(f"Chart {chart_name!r} not found at {chart_dir} — skipping.")
                continue
            chart_values = (
                subst_values_by_chart.get(chart_name, {})
                if subst_values_by_chart is not None
                else (subst_values or {})
            )
            chart = self.Chart(
                self.k8s, chart_name, namespace, chart_dir, chart_values, running_labels,
            )
            chart.install()
            self.installed_charts[chart_name] = chart

        self.k8s.bind_privileged_scc(namespace, list(self.installed_charts))
        self.k8s.dump_csi_workloads(namespace)

        for chart in self.installed_charts.values():
            chart.wait()

    def _ensure_chart_repo(self):
        """Cache the published repo index so charts can resolve their vast-common dependency."""
        logger.info(f"helm repo add {_VAST_HELM_REPO_NAME} {_VAST_HELM_REPO_URL}")
        self.k8s.helm[
            "repo", "add", _VAST_HELM_REPO_NAME, _VAST_HELM_REPO_URL, "--force-update",
        ] & FG
        self.k8s.helm["repo", "update", _VAST_HELM_REPO_NAME] & FG

    def wait(self, *_, **__):
        raise NotImplementedError("Call wait() on individual Chart objects.")

    def __getattr__(self, item):
        try:
            return self.installed_charts[item]
        except KeyError:
            raise AttributeError(item)
