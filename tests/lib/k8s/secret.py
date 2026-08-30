from typing import Optional

from easypy.collections import listify
from plumbum import FG

from lib.logging import logger

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

    def ensure_docker_registry(
        self, namespace, docker_server: str, username: str, password: str, *, name: Optional[str] = None
    ):
        name = resource_name("secret", name)
        for ns in listify(namespace):
            if self.get(name=name, namespace=ns):
                logger.info(f"Secret {name!r} already exists in {ns!r}. Skipping.")
            else:
                self.k8s.kubectl[
                    "create", self.resource_type, "docker-registry", name, "-n", ns,
                    "--docker-server", docker_server,
                    "--docker-username", username,
                    "--docker-password", password,
                ] & FG

    def create_from_file(self, namespace: str, file_path: str, key_name: str, *, name: Optional[str] = None):
        name = resource_name("secret", name)
        self.k8s.kubectl[
            "create", self.resource_type, "generic", name,
            "-n", namespace, f"--from-file={key_name}={file_path}",
        ] & FG
        if name != MGMT_SECRET:
            self.k8s.creation_recorder.record(self.resource_type, name, namespace)
        return name
