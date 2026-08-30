from typing import Optional

from plumbum import FG

from lib.builders.base import resource_name
from lib.k8s._base import KubernetesResource
from lib.constants import MGMT_SECRET


class Secret(KubernetesResource):
    resource_type = "secret"

    def create(
        self,
        namespace: str,
        *,
        name: Optional[str] = None,
        files: Optional[dict] = None,
        **literal_kwargs,
    ):
        name = resource_name("secret", name)
        literal_params = [f"--from-literal={k}={v}" for k, v in literal_kwargs.items()]
        file_params = [f"--from-file={k}={path}" for k, path in (files or {}).items()]
        self.k8s.kubectl[
            ["create", self.resource_type, "generic", name, "-n", namespace]
            + literal_params
            + file_params
        ] & FG
        if name != MGMT_SECRET:
            self.k8s.creation_recorder.record(self.resource_type, name, namespace)
        return name

    def ensure(self, *, namespace: str, name: Optional[str] = None, **literal_kwargs):
        name = resource_name("secret", name)
        if self.get(name=name, namespace=namespace):
            return name
        literal_params = [f"--from-literal={k}={v}" for k, v in literal_kwargs.items()]
        self.k8s.kubectl[
            ["create", self.resource_type, "generic", name, "-n", namespace] + literal_params
        ] & FG
        return name

    def delete(self, name: str, namespace: str = "default", **_):
        self.k8s.kubectl[
            "delete", self.resource_type, name, "-n", namespace, "--ignore-not-found"
        ] & FG
