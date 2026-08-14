"""
KubernetesResource base and K8S facade.

K8S holds references to all resource managers.
KubernetesResource provides apply/get/delete/patch/wait/describe backed by kubectl.
"""
from __future__ import annotations

import re
import time
import yaml
from threading import RLock
from typing import List, Optional, Union

from easypy.bunch import Bunch, unbunchify
try:
    from easypy.caching import cached_property
except ImportError:
    from functools import cached_property
from easypy.collections import listify, ListCollection, iterable
from easypy.exceptions import TException
from easypy.resilience import retrying
try:
    from easypy.sync import with_my_lock
except ImportError:
    from functools import wraps

    def with_my_lock(func):
        @wraps(func)
        def inner(self, *args, **kwargs):
            with self._lock:
                return func(self, *args, **kwargs)
        return inner
from easypy.timing import PredicateNotSatisfied, wait
from easypy.units import MINUTE
from plumbum import FG, local
from plumbum.commands.processes import ProcessExecutionError

from e2e.k8s.ops_recording import CreationRecorder
from e2e.constants import CSI_NAMESPACE
from e2e.logging import logger


class WaitResourceFailed(TException, PredicateNotSatisfied):
    template = (
        "{num_failed}/{num_total} {resource}(s) failed to satisfy {condition} "
        "({target}); found: {found}"
    )


class KubernetesResource:
    resource_type: str = None
    record_on_create: bool = True

    def __init__(self, k8s: "K8S"):
        self.k8s = k8s
        self._lock = k8s._lock

    def _namespace_from_manifest(self, manifest) -> Optional[str]:
        if self.resource_type in ("storageclass", "pv", "namespace"):
            return None
        return manifest.metadata.get("namespace", "default")

    def _record_manifest(self, manifest, record_on_create=None) -> Bunch:
        should_record = record_on_create if record_on_create is not None else self.record_on_create
        if should_record:
            ns = self._namespace_from_manifest(manifest)
            self.k8s.creation_recorder.record(
                self.resource_type,
                manifest.metadata.name,
                ns,
            )
        return manifest

    def _apply_and_record(self, manifest, record_on_create=None) -> Bunch:
        if not isinstance(manifest, Bunch):
            manifest = Bunch.from_dict(manifest) if isinstance(manifest, dict) else manifest
        self.apply([manifest])
        return self._record_manifest(manifest, record_on_create=record_on_create)

    @with_my_lock
    def apply(self, objects):
        fpath = self.k8s._next_object_yaml_path(self.resource_type)
        with fpath.open("w") as f:
            yaml.dump_all(unbunchify(objects), f)
        (self.k8s.kubectl["apply", "-f", "-"] << fpath.read()) & FG

    def create(self, *args, **kwargs):
        raise NotImplementedError()

    @with_my_lock
    def get(
        self,
        name: Optional[Union[str, List[str]]] = None,
        namespace: Optional[str] = "default",
        labels: Optional[dict] = None,
    ):
        many = True
        args = ["--output=json", "get", self.resource_type]
        if labels:
            labels_str = ",".join(f"{k}={v}" for k, v in labels.items())
            args.extend(["-l", labels_str])
        if name:
            name = listify(name)
            if len(name) == 1:
                many = False
            args.extend(name)
        if namespace:
            args.extend(["-n", namespace])
        try:
            res = Bunch.from_json(self.k8s.kubectl(*args))
        except ProcessExecutionError as exc:
            if "not found" in str(exc):
                return []
            raise
        if many:
            res = ListCollection(res["items"])
        return res

    def ensure(self, *args, **kwargs):
        self.delete(*args, **kwargs)
        self.create(*args, **kwargs)

    def delete(self, name: str, namespace: Optional[str] = "default", force: bool = False, wait: bool = True, **_):
        args = ["delete", self.resource_type, name, "--ignore-not-found"]
        if namespace is not None:
            args.extend(["-n", namespace])
        if force:
            args.extend(["--force", "--grace-period=0"])
        if not wait:
            args.append("--wait=false")
        self.k8s.kubectl[args] & FG

    def delete_from_path(self, path: str, ignore_not_found: bool = True):
        try:
            self.k8s.kubectl["delete", "-f", path] & FG
        except ProcessExecutionError:
            if not ignore_not_found:
                raise

    def patch(self, name: str, patch: dict, namespace: str = "default"):
        res = self.get(name, namespace)
        if not res:
            raise TException(f"Resource {self.resource_type}/{name} not found in namespace {namespace}")
        if iterable(res):
            raise TException(f"Multiple resources found for {self.resource_type}/{name} in namespace {namespace}")

        def _deep_patch(d, u):
            for k, v in u.items():
                if isinstance(v, (dict, Bunch)):
                    d[k] = _deep_patch(d.get(k, {}), v)
                else:
                    d[k] = v
            return d

        _deep_patch(res, patch)
        self.apply([res])

    @staticmethod
    def _wait_target(name, namespace, labels) -> str:
        bits = [f"namespace={namespace or 'all'}"]
        if name:
            bits.append(f"name={','.join(str(n) for n in listify(name))}")
        if labels:
            bits.append("labels=" + ",".join(f"{k}={v}" for k, v in labels.items()))
        return " ".join(bits)

    @staticmethod
    def _object_name(obj) -> str:
        meta = obj.get("metadata") if hasattr(obj, "get") else getattr(obj, "metadata", None)
        if meta is None:
            return "<unknown>"
        return meta.get("name") or getattr(meta, "name", None) or "<unknown>"

    @classmethod
    def _object_status_line(cls, obj) -> str:
        name = cls._object_name(obj)
        status = obj.get("status") if hasattr(obj, "get") else getattr(obj, "status", None)
        if not status:
            return name
        phase = status.get("phase") or ""
        extras = []
        ready = status.get("readyToUse")
        if ready is False:
            extras.append("readyToUse=false")
        for cs in status.get("containerStatuses") or []:
            cname = cs.get("name") or "container"
            state = cs.get("state") or {}
            waiting = state.get("waiting") or {}
            if waiting:
                extras.append(f"{cname}:{waiting.get('reason') or waiting.get('message') or 'waiting'}")
            terminated = state.get("terminated") or {}
            if terminated and terminated.get("reason") not in (None, "Completed"):
                extras.append(f"{cname}:{terminated.get('reason')}")
        extra = f" ({', '.join(extras)})" if extras else ""
        phase_s = f" phase={phase}" if phase else ""
        return f"{name}{phase_s}{extra}"

    def _found_detail(self, res_list) -> str:
        if not res_list:
            return "no matching objects"
        return "; ".join(self._object_status_line(r) for r in res_list)

    def _wait_failed(self, *, num_failed, num_total, condition, name, namespace, labels, res_list, error_msg=None):
        found = self._found_detail(res_list)
        names = [self._object_name(r) for r in res_list] if res_list else []
        return WaitResourceFailed(
            num_failed=num_failed,
            num_total=num_total,
            resource=self.resource_type,
            condition=condition,
            target=self._wait_target(name, namespace, labels),
            found=found,
            namespace=namespace,
            resource_name=name or (",".join(names) if names else None),
            labels=labels,
            tip=error_msg or None,
        )

    def _dump_wait_context(self, namespace):
        ns_args = ["-n", namespace] if namespace else []
        commands = [
            ["get", self.resource_type, *ns_args, "-o", "wide"],
            ["get", "events", *ns_args, "--sort-by=.lastTimestamp"],
        ]
        for args in commands:
            try:
                logger.error(f"$ kubectl {' '.join(args)}")
                logger.error(self.k8s.kubectl(*args) or "(empty)")
            except Exception as exc:
                logger.error(f"kubectl {' '.join(args)} failed: {exc}")

    def wait(
        self,
        timeout: int = MINUTE,
        name: Optional[Union[str, List[str]]] = None,
        namespace: Optional[str] = "default",
        labels: Optional[dict] = None,
        condition: Optional[str] = "Running",
        error_msg: Optional[str] = False,
        show_error_log: bool = True,
    ):
        def _wait_present():
            res = self.get(name, namespace, labels)
            res_list = listify(res)
            num_total = len(res_list)
            try:
                if not (statuses := [r["status"] for r in res_list]):
                    raise self._wait_failed(
                        num_failed=0, num_total=0, condition=condition,
                        name=name, namespace=namespace, labels=labels,
                        res_list=res_list, error_msg=error_msg,
                    )
            except KeyError:
                return res  # no status field — presence is enough
            if hasattr(statuses[0], "bucketReady"):
                num_failed = len([r for r in res_list if r.status.bucketReady is False])
            else:
                expected = ["running", "bound"]
                num_failed = len([
                    r for r in res_list
                    if (
                        not r["status"].get("readyToUse", True)
                        or r["status"].get("phase", "running").lower() not in expected
                    )
                ])
            if num_failed:
                raise self._wait_failed(
                    num_failed=num_failed, num_total=num_total, condition=condition,
                    name=name, namespace=namespace, labels=labels,
                    res_list=res_list, error_msg=error_msg,
                )
            return res

        def _wait_absent():
            if res := listify(self.get(name, namespace, labels)):
                raise self._wait_failed(
                    num_failed=len(res), num_total="N/A", condition=condition,
                    name=name, namespace=namespace, labels=labels,
                    res_list=res, error_msg=error_msg,
                )
            return True

        try:
            if condition.lower() == "deleted":
                return wait(timeout, _wait_absent, message=error_msg)
            return wait(timeout, _wait_present, message=error_msg)
        except WaitResourceFailed:
            if show_error_log:
                self._dump_wait_context(namespace)
                self.k8s.show_errors()
            raise

    def describe(self, name: str, namespace: Optional[str] = "default"):
        self.k8s.kubectl["describe", self.resource_type, name, "-n", namespace] & FG


class K8S:
    """
    Facade that wires together a kubectl command and all resource managers.
    Imports are deferred to avoid circular dependencies between submodules.
    """

    def __init__(self, kube_cmd, helm_cmd=None):
        self.kubectl = kube_cmd
        self._helm = helm_cmd
        self.k8s_version = None
        self._object_idx = 0
        self._lock = RLock()
        self._creation_recorder = CreationRecorder()
        self._start_time = time.time()

    @property
    def creation_recorder(self) -> CreationRecorder:
        return self._creation_recorder

    def clear_creation_recordings(self) -> None:
        self._creation_recorder.clear()

    def cleanup_creation_recordings(self, *, parallel: bool = True) -> None:
        self._creation_recorder.cleanup(self, parallel=parallel)

    def _next_object_yaml_path(self, resource_type: str):
        with self._lock:
            self._object_idx += 1
            idx = self._object_idx
        return local.path("/tmp")[f"csi-e2e.{resource_type}.{idx}.yaml"]

    def __repr__(self):
        return f"K8S[{self.kubectl}]"

    __str__ = __repr__

    @property
    def helm(self):
        assert self._helm, "Helm command is not provided."
        return self._helm.with_env(**(self.kubectl.env or {}))

    # ------------------------------------------------------------------
    # Resource managers (lazy, one per kubectl resource type)
    # ------------------------------------------------------------------

    @cached_property
    def secrets(self):
        from e2e.k8s.secret import Secret
        return Secret(self)

    @cached_property
    def namespaces(self):
        from e2e.k8s.workloads import Namespace
        return Namespace(self)

    @cached_property
    def pods(self):
        from e2e.k8s.workloads import Pod
        return Pod(self)

    @cached_property
    def deployments(self):
        from e2e.k8s.workloads import Deployment
        return Deployment(self)

    @cached_property
    def sts(self):
        from e2e.k8s.workloads import StatefulSet
        return StatefulSet(self)

    @cached_property
    def pvcs(self):
        from e2e.k8s.storage import PersistentVolumeClaim
        return PersistentVolumeClaim(self)

    @cached_property
    def pvs(self):
        from e2e.k8s.storage import PersistentVolume
        return PersistentVolume(self)

    @cached_property
    def storageclasses(self):
        from e2e.k8s.storage import StorageClass
        return StorageClass(self)

    @cached_property
    def volumesnapshots(self):
        from e2e.k8s.storage import VolumeSnapshot
        return VolumeSnapshot(self)

    @cached_property
    def volumesnapshotcontents(self):
        from e2e.k8s.storage import VolumeSnapshotContent
        return VolumeSnapshotContent(self)

    @cached_property
    def helmvalues(self):
        from e2e.k8s.helm import HelmValues
        return HelmValues(self)

    @cached_property
    def bucketclaims(self):
        from e2e.k8s.cosi import BucketClaim
        return BucketClaim(self)

    @cached_property
    def bucketaccessclasses(self):
        from e2e.k8s.cosi import BucketAccessClass
        return BucketAccessClass(self)

    @cached_property
    def bucketaccesses(self):
        from e2e.k8s.cosi import BucketAccess
        return BucketAccess(self)

    @cached_property
    def vastcsidrivers(self):
        from e2e.k8s.vast import VastCSIDriver
        return VastCSIDriver(self)

    @cached_property
    def vastclusters(self):
        from e2e.k8s.vast import VastCluster
        return VastCluster(self)

    @cached_property
    def vaststorages(self):
        from e2e.k8s.vast import VastStorage
        return VastStorage(self)

    @cached_property
    def vvrs(self):
        from e2e.k8s.replication import VastVolumeReplication
        return VastVolumeReplication(self)

    @cached_property
    def vscrs(self):
        from e2e.k8s.replication import VastStorageClassReplication
        return VastStorageClassReplication(self)

    @cached_property
    def vrcs(self):
        from e2e.k8s.replication import VastReplicationContent
        return VastReplicationContent(self)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def bind_privileged_scc(self, namespace: str, releases: list[str]) -> None:
        """Allow CSI controller/node SAs to run privileged pods on OpenShift."""
        try:
            self.kubectl("get", "clusterrole", "system:openshift:scc:privileged")
        except ProcessExecutionError:
            logger.info("No OpenShift privileged SCC; skipping RoleBindings")
            return
        objects = []
        for release in releases:
            if release not in ("vastcsi", "vastblock"):
                continue
            for kind in ("controller", "node"):
                sa = f"{release}-vast-{kind}-sa"
                objects.append({
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {"name": f"{sa}-scc", "namespace": namespace},
                    "subjects": [{"kind": "ServiceAccount", "name": sa, "namespace": namespace}],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": "system:openshift:scc:privileged",
                    },
                })
        if not objects:
            return
        path = self._next_object_yaml_path("rolebinding")
        with path.open("w") as f:
            yaml.dump_all(objects, f)
        (self.kubectl["apply", "-f", "-"] << path.read()) & FG
        logger.info(f"Bound privileged SCC in {namespace} for {releases}")

    def dump_csi_workloads(self, namespace: str) -> None:
        try:
            out = self.kubectl("get", "deploy,ds,pods,events", "-n", namespace, "-o", "wide")
            logger.info(f"Workloads in {namespace}:\n{out}")
        except Exception as exc:
            logger.warning(f"could not list workloads in {namespace}: {exc}")

    def show_errors(self):
        pattern = re.compile(r"ERROR.*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})", re.DOTALL)
        since = max(1, round((time.time() - self._start_time) / 60))
        checks = [
            ("csi-vast-controller", "csi-vast-plugin"),
            ("csi-vast-node", "csi-vast-plugin"),
            ("block-vast-controller", "csi-vast-plugin"),
            ("block-vast-node", "csi-vast-plugin"),
            ("cosi-provisioner", "cosi-vast-plugin"),
        ]
        for app, container in checks:
            for pod in self.pods.get(namespace=CSI_NAMESPACE, labels={"app": app}) or []:
                name = pod.metadata.name
                try:
                    logs = self.kubectl(
                        "logs", name, "-c", container, "-n", CSI_NAMESPACE, f"--since={since}m"
                    )
                except Exception:
                    continue
                if match := pattern.search(logs):
                    logger.error(f"Noticeable errors in {name}:\n{match.group(0)}")
