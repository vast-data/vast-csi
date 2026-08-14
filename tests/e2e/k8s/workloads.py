import shlex
from typing import List, Optional

from easypy.resilience import retrying
from plumbum import FG
from plumbum.commands.processes import ProcessExecutionError

from e2e.builders.base import resource_name
from e2e.k8s._base import KubernetesResource


class Namespace(KubernetesResource):
    resource_type = "namespace"

    def create(self, name: Optional[str] = None):
        name = resource_name("namespace", name)
        self.k8s.kubectl["create", "ns", name] & FG
        self.k8s.creation_recorder.record(self.resource_type, name, namespace=None)
        return name

    def allow_privileged(self, name: str = "default"):
        """CSI pods need privileged PSA. OpenShift CRC restricts namespaces by default."""
        self.k8s.kubectl[
            "label", "ns", name, "--overwrite",
            "pod-security.kubernetes.io/enforce=privileged",
            "pod-security.kubernetes.io/audit=privileged",
            "pod-security.kubernetes.io/warn=privileged",
            "security.openshift.io/scc.podSecurityLabelSync=false",
        ] & FG

    def delete(self, name: str, **_):
        self.k8s.kubectl["delete", self.resource_type, name, "--ignore-not-found"] & FG


class Pod(KubernetesResource):
    resource_type = "pod"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)

    @retrying.debug(
        times=5,
        acceptable=ProcessExecutionError,
        pred=lambda e: "EOF" in str(e),
    )
    def exec(self, pod_name: str, command: str):
        """Run *command* in a pod via kubectl exec. Use this to inspect volume data."""
        return self.k8s.kubectl(*["exec", "-t", pod_name, "--"] + shlex.split(command))

    def ls(self, pod_name: str, path: str = "/shared") -> list[str]:
        """List files at *path* inside a running pod (never mount on the test host)."""
        out = (self.exec(pod_name, f"ls -1 {path}") or "").strip()
        return [name for name in out.splitlines() if name]

    def read(self, pod_name: str, path: str, *, head: int = 1) -> str:
        """Read a file inside a running pod via kubectl exec."""
        cmd = f"head -{head} {path}" if head else f"cat {path}"
        return (self.exec(pod_name, cmd) or "").strip()


class Deployment(KubernetesResource):
    resource_type = "deployment"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)


class StatefulSet(KubernetesResource):
    resource_type = "statefulset"

    def create(self, builder, record_on_create=None):
        return self._apply_and_record(builder.result(), record_on_create=record_on_create)
