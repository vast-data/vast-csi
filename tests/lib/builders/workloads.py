"""Builders for Pod, Deployment, and StatefulSet manifests."""
from __future__ import annotations

from typing import Any, List, Optional

from lib.builders.base import Builder, resource_name
from lib.constants import BUSYBOX_IMAGE

_DEFAULT_COMMAND = ["sh", "-c", "while true; do date -Iseconds >> /shared/$HOSTNAME; sleep 1; done"]


def _workload_labels(name: str, extra: Optional[dict]) -> dict:
    base = {"app": name}
    if extra:
        base.update(extra)
    return base


class PodBuilder(Builder):
    """Fluent builder for a Pod manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        container_name: str,
        image: str,
        command: Optional[List[str]] = None,
    ) -> "PodBuilder":
        body: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": resource_name("pod", name)},
            "spec": {
                "containers": [
                    {
                        "name": container_name,
                        "image": image,
                        "command": command or _DEFAULT_COMMAND,
                    }
                ],
            },
        }
        return cls._from_body(body)

    def with_volume(
        self,
        volume_name: Optional[str],
        mount_path: Optional[str],
        volume: Optional[dict],
    ) -> "PodBuilder":
        if volume_name is None:
            return self
        assert mount_path and volume, "volume_name, mount_path and volume must be provided together"
        self._body["spec"]["containers"][0]["volumeMounts"] = [
            {"mountPath": mount_path, "name": volume_name}
        ]
        self._body["spec"]["volumes"] = [volume]
        return self

    def with_volume_device(
        self,
        volume_name: str,
        device_path: str,
        volume: dict,
    ) -> "PodBuilder":
        """Use volumeDevices (raw block) instead of volumeMounts."""
        self._body["spec"]["containers"][0]["volumeDevices"] = [
            {"name": volume_name, "devicePath": device_path}
        ]
        self._body["spec"]["volumes"] = [volume]
        return self

    def with_args(self, args: Optional[List[str]]) -> "PodBuilder":
        if args:
            self._body["spec"]["containers"][0]["args"] = args
        return self


class DeploymentBuilder(Builder):
    """Fluent builder for a Deployment manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        pvc: str,
        replicas: int,
        command: Optional[List[str]] = None,
        extra_labels: Optional[dict] = None,
    ) -> "DeploymentBuilder":
        name = resource_name("deployment", name)
        labels = _workload_labels(name, extra_labels)
        body: dict[str, Any] = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": name},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": {"role": "csitest", **labels}},
                    "spec": {
                        "containers": [
                            {
                                "name": "my-frontend",
                                "image": BUSYBOX_IMAGE,
                                "command": command or _DEFAULT_COMMAND,
                                "volumeMounts": [{"mountPath": "/shared", "name": "my-shared-volume"}],
                            }
                        ],
                        "volumes": [{"name": "my-shared-volume", "persistentVolumeClaim": {"claimName": pvc}}],
                    },
                },
            },
        }
        return cls._from_body(body)


class StatefulSetBuilder(Builder):
    """builder for a StatefulSet manifest."""

    @classmethod
    def new(
        cls,
        *,
        name: Optional[str] = None,
        pvc: str,
        replicas: int,
        command: Optional[List[str]] = None,
        extra_labels: Optional[dict] = None,
    ) -> "StatefulSetBuilder":
        name = resource_name("statefulset", name)
        labels = _workload_labels(name, extra_labels)
        body: dict[str, Any] = {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": name},
            "spec": {
                "replicas": replicas,
                "selector": {"matchLabels": labels},
                "serviceName": f"{name}-service",
                "template": {
                    "metadata": {"labels": {"role": "csitest", **labels}},
                    "spec": {
                        "containers": [
                            {
                                "name": "my-frontend",
                                "image": BUSYBOX_IMAGE,
                                "command": command or _DEFAULT_COMMAND,
                                "volumeMounts": [{"mountPath": "/shared", "name": "my-shared-volume"}],
                            }
                        ],
                        "volumes": [{"name": "my-shared-volume", "persistentVolumeClaim": {"claimName": pvc}}],
                    },
                },
            },
        }
        return cls._from_body(body)
