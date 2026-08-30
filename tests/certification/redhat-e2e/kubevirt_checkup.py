"""KubeVirt storage checkup implemented with the tests/lib K8S client."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Optional

import yaml
from plumbum.commands.processes import ProcessExecutionError

from lib.k8s import K8S

GOLDEN_IMAGE_NAME = "alpine-golden-image"
LEGACY_GOLDEN_IMAGE_NAMES = ("fedora-coreos-golden-image",)
IMAGE_NS = "openshift-virtualization-os-images"
DEFAULT_STORAGE_CLASS = "vastdata-filesystem"
DEFAULT_SC_ANNOTATION = "storageclass.kubernetes.io/is-default-class"
CHECKUP_IMAGE = "quay.io/kiagnose/kubevirt-storage-checkup:main"
CHECKUP_JOB = "storage-checkup"
CHECKUP_CONFIG = "storage-checkup-config"
CHECKUP_SA = "storage-checkup-sa"
ALPINE_IMAGE_REPO = "quay.io/kubevirtci/alpine-with-test-tooling-container-disk"
ALPINE_IMAGE_DIGEST = "sha256:8c8e8bb6cd81c75e492c678abb3e5f186d52eba2174ebabc328316250acfea58"
GOLDEN_IMAGE_SIZE = "1Gi"
KUBEVIRT_STABLE_URL = (
    "https://storage.googleapis.com/kubevirt-prow/release/kubevirt/kubevirt/stable.txt"
)
CDI_OPERATOR_URL = (
    "https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-operator.yaml"
)
CDI_CR_URL = (
    "https://github.com/kubevirt/containerized-data-importer/releases/latest/download/cdi-cr.yaml"
)
KUBEVIRT_SAS = (
    "kubevirt-operator",
    "kubevirt-controller",
    "virt-controller",
    "virt-api",
    "virt-handler",
)
KUBEVIRT_RESTART_LABELS = (
    "kubevirt.io=virt-controller",
    "kubevirt.io=virt-api",
    "kubevirt.io=virt-handler",
)
DV_READY_TIMEOUT_SECONDS = 90 * 60
PROGRESS_INTERVAL_SECONDS = 20
# CRC NFS snapshot clones + two concurrent guest-agent boots exceed kiagnose's 30m default.
CHECKUP_TIMEOUT = "90m"
VMI_TIMEOUT = "25m"
# Single extra golden-image boot; CRC cannot clone+boot two VMs in parallel.
CHECKUP_NUM_VMS = "1"
# kiagnose image pull (~170MB) plus scheduling on CRC often exceeds 30s.
CHECKUP_POD_START_TIMEOUT_SECONDS = 5 * 60
# virt-handler advertises this only while /dev/kvm is present on the node.
KVM_DEVICE_RESOURCE = "devices.kubevirt.io/kvm"


def _print(msg: str) -> None:
    print(msg, flush=True)


def _text(value) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _exception_text(exc: BaseException) -> str:
    """Include process output omitted by ProcessExecutionError.__str__."""
    return "\n".join(
        part
        for part in (
            str(exc),
            _text(getattr(exc, "stdout", "")),
            _text(getattr(exc, "stderr", "")),
        )
        if part
    )


def _oc(k8s: K8S, *args: str, ignore: bool = False) -> str:
    try:
        out = _text(k8s.kubectl(*args))
        if out.strip():
            _print(out.rstrip())
        return out
    except ProcessExecutionError as exc:
        detail = _text(getattr(exc, "stdout", "")) + _text(getattr(exc, "stderr", "")) or str(exc)
        if ignore:
            _print(f"[WARN] oc {' '.join(args)} failed: {detail.strip()[:500]}")
            return ""
        if detail.strip():
            _print(detail.rstrip())
        raise


def _apply(k8s: K8S, objects) -> None:
    if not isinstance(objects, (list, tuple)):
        objects = [objects]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump_all(list(objects), fh)
        path = fh.name
    _oc(k8s, "apply", "-f", path)


def _exists(k8s: K8S, resource_type: str, name: str, namespace: Optional[str] = None) -> bool:
    try:
        return bool(k8s.resource(resource_type).get(name, namespace=namespace))
    except ProcessExecutionError as exc:
        if _resource_not_found(exc):
            return False
        raise


def _missing_resource_type(exc: BaseException) -> bool:
    msg = _exception_text(exc).lower()
    return (
        "doesn't have a resource type" in msg
        or "no matches for kind" in msg
        or "could not find the requested resource" in msg
    )


def _resource_not_found(exc: BaseException) -> bool:
    msg = _exception_text(exc).lower()
    return _missing_resource_type(exc) or "notfound" in msg or "not found" in msg


def _safe_delete(k8s: K8S, resource_type: str, name: str, *, namespace: str, wait: bool = True) -> None:
    if not _exists(k8s, resource_type, name, namespace=namespace):
        return
    args = ["delete", resource_type, name, "--ignore-not-found", "-n", namespace]
    if not wait:
        args.append("--wait=false")
    _oc(k8s, *args, ignore=True)


def _safe_list(k8s: K8S, resource_type: str, *, namespace: str):
    try:
        return k8s.resource(resource_type).get(namespace=namespace) or []
    except ProcessExecutionError as exc:
        if _resource_not_found(exc):
            return []
        raise


def _wait_condition(
    k8s: K8S,
    resource_type: str,
    name: str,
    *,
    namespace: Optional[str] = None,
    condition: str = "Available",
    timeout: str = "15m",
) -> None:
    args = ["wait", resource_type, name, f"--for=condition={condition}", f"--timeout={timeout}"]
    if namespace:
        args.extend(["-n", namespace])
    _oc(k8s, *args)


def _merge_patch(k8s: K8S, resource_type: str, name: str, patch: dict, *, namespace: Optional[str] = None) -> None:
    args = ["patch", resource_type, name, "--type=merge", "-p", json.dumps(patch)]
    if namespace:
        args.extend(["-n", namespace])
    _oc(k8s, *args)


def _grant_privileged_scc(k8s: K8S, namespace: str, sa: str) -> None:
    _oc(k8s, "adm", "policy", "add-scc-to-user", "privileged", "-n", namespace, "-z", sa, ignore=True)


def _kubevirt_release() -> str:
    if release := os.environ.get("RELEASE"):
        return release
    with urllib.request.urlopen(KUBEVIRT_STABLE_URL, timeout=30) as resp:
        return resp.read().decode("utf-8").strip()


def _duration_seconds(value: str) -> int:
    """Parse a Go-style duration ("8h", "90m", "30s") into seconds."""
    text = value.strip().lower()
    units = {"h": 3600, "m": 60, "s": 1}
    total = 0
    number = ""
    for char in text:
        if char.isdigit():
            number += char
            continue
        if char in units and number:
            total += int(number) * units[char]
            number = ""
        else:
            raise ValueError(f"Unsupported duration: {value!r}")
    if number:
        total += int(number)
    if not total:
        raise ValueError(f"Unsupported duration: {value!r}")
    return total


def _hardware_virtualization_available(k8s: K8S) -> bool:
    """Report whether any node exposes /dev/kvm.

    Software emulation (TCG) is 10-50x slower than KVM: a guest may never
    reach the guest agent within the checkup VMI timeout, so the boot check
    fails even though storage is healthy.
    """
    try:
        payload = json.loads(_text(k8s.kubectl("get", "nodes", "-o", "json")) or "{}")
    except (ProcessExecutionError, ValueError) as exc:
        _print(f"[WARN] Could not query nodes for KVM support: {exc}")
        return False
    for node in payload.get("items") or []:
        allocatable = ((node.get("status") or {}).get("allocatable") or {})
        raw = str(allocatable.get(KVM_DEVICE_RESOURCE) or "0")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits and int(digits) > 0:
            name = ((node.get("metadata") or {}).get("name")) or "?"
            _print(f"[INFO] Node {name} exposes {KVM_DEVICE_RESOURCE}={raw}")
            return True
    return False


def _kubectl_env(k8s: K8S) -> dict[str, str]:
    env = os.environ.copy()
    bound = getattr(k8s.kubectl, "env", None) or {}
    env.update({str(key): str(value) for key, value in bound.items()})
    return env


def _kubectl_argv(k8s: K8S, *args: str) -> list[str]:
    cmd = k8s.kubectl[args]
    formulate = getattr(cmd, "formulate", None)
    if callable(formulate):
        return [str(part) for part in formulate()]
    inner = getattr(k8s.kubectl, "cmd", k8s.kubectl)
    exe = getattr(inner, "executable", None) or "oc"
    return [str(exe), *args]


def _follow_pod_logs(k8s: K8S, pod_name: str, namespace: str) -> str:
    """Follow checkup logs to the terminal and return the full text for the RH artifact."""
    proc = subprocess.Popen(
        _kubectl_argv(k8s, "logs", "-f", f"pod/{pod_name}", "-n", namespace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=_kubectl_env(k8s),
    )
    chunks: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        chunks.append(line)
    proc.wait()
    return "".join(chunks)


def format_redhat_checkup_log(
    *,
    namespace: str,
    pod_name: str,
    job_logs: str,
    configmap_yaml: str,
    final_phase: str,
    succeeded: str,
) -> str:
    """Red Hat submission log: kiagnose job output + ConfigMap, in the old `oc` script shape."""
    logs = (job_logs or "").rstrip() + "\n"
    cm = (configmap_yaml or "").rstrip() + "\n"
    return (
        "=========================================\n"
        f"+ oc logs -f pod/{pod_name} -n {namespace}\n"
        f"{logs}"
        "+ echo ==========================================\n"
        "==========================================\n"
        "+ echo '[INFO] Final storage checkup result:'\n"
        "[INFO] Final storage checkup result:\n"
        f"+ oc get configmap {CHECKUP_CONFIG} -n {namespace} -o yaml\n"
        f"{cm}"
        f"++ oc get pod {pod_name} -n {namespace} -o 'jsonpath={{.status.phase}}'\n"
        f"+ FINAL_PHASE={final_phase}\n"
        f"++ oc get configmap {CHECKUP_CONFIG} -n {namespace} "
        "-o 'jsonpath={.data.status\\.succeeded}'\n"
        f"+ SUCCEEDED={succeeded}\n"
    )


def _resource_or_none(obj):
    if not obj or isinstance(obj, list):
        return None
    return obj


def _dv_phase_and_download(dv) -> tuple[str, str]:
    dv = _resource_or_none(dv)
    if not dv:
        return "Unknown", ""
    status = dv.get("status") or {}
    phase = str(status.get("phase") or "Unknown")
    progress = str(status.get("progress") or "").strip()
    if progress.upper() in {"", "N/A", "NA"}:
        progress = ""
    return phase, progress


def _dv_is_ready(dv) -> bool:
    dv = _resource_or_none(dv)
    if not dv:
        return False
    phase, _ = _dv_phase_and_download(dv)
    return phase == "Succeeded" or _condition_status(dv, "Ready") == "True"


def _importer_pod_name(k8s: K8S, namespace: str, dv=None) -> str:
    pods = k8s.pods.get(namespace=namespace) or []
    importers = [pod for pod in pods if str(pod.metadata.name).startswith("importer-")]
    dv = _resource_or_none(dv)
    uid = str(dv.metadata.uid) if dv else ""
    if uid:
        matched = [pod for pod in importers if uid in str(pod.metadata.name)]
        if matched:
            importers = matched
    running = [
        pod for pod in importers
        if str((pod.get("status") or {}).get("phase") or "") == "Running"
    ]
    chosen = running or importers
    return chosen[0].metadata.name if chosen else ""


def _last_log_percent(k8s: K8S, pod_name: str, namespace: str, needle: str) -> str:
    try:
        out = _text(k8s.kubectl("logs", f"pod/{pod_name}", "-n", namespace, "--tail=120"))
    except ProcessExecutionError:
        return ""
    percent = ""
    for line in out.splitlines():
        if needle not in line:
            continue
        token = line.strip().split()[-1].rstrip("%")
        try:
            float(token)
        except ValueError:
            continue
        percent = token
    return percent


_last_percents: dict[str, dict[str, str]] = {}


def _fmt_percent(value: str) -> str:
    value = (value or "").strip().rstrip("%")
    if not value:
        return ""
    try:
        float(value)
    except ValueError:
        return ""
    return f"{value}%"


def _print_dv_progress(k8s: K8S, name: str, namespace: str, dv) -> tuple[str, bool]:
    phase, download = _dv_phase_and_download(dv)
    ready = _dv_is_ready(dv)
    pod_name = _importer_pod_name(k8s, namespace, dv)
    if not download and pod_name:
        download = _last_log_percent(k8s, pod_name, namespace, "prometheus.go")
    convert = _last_log_percent(k8s, pod_name, namespace, "qemu.go") if pod_name else ""
    seen = _last_percents.setdefault(name, {})
    prev_dl = seen.get("download")
    if pct := _fmt_percent(download):
        try:
            if prev_dl and float(pct.rstrip("%")) + 5 < float(str(prev_dl).rstrip("%")):
                seen.pop("convert", None)
        except ValueError:
            pass
        seen["download"] = pct
    if pct := _fmt_percent(convert):
        seen["convert"] = pct
    parts = [f"{key}={seen[key]}" for key in ("download", "convert") if key in seen]
    if parts:
        _print(f"[INFO] {name}: {' '.join(parts)}")
    return phase, ready


def _wait_datavolume_ready(
    k8s: K8S,
    name: str,
    namespace: str,
    *,
    timeout: int = DV_READY_TIMEOUT_SECONDS,
    interval: int = PROGRESS_INTERVAL_SECONDS,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        dv = k8s.resource("datavolume").get(name, namespace=namespace)
        phase, done = _print_dv_progress(k8s, name, namespace, dv)
        if done:
            _print(f"[INFO] DataVolume {name} is ready")
            return
        if phase == "Failed":
            _oc(k8s, "describe", "datavolume", name, "-n", namespace, ignore=True)
            raise RuntimeError(f"DataVolume {name} failed")
        time.sleep(interval)
    _print(f"[ERROR] Timeout waiting for DataVolume {name} to become ready")
    _oc(k8s, "describe", "datavolume", name, "-n", namespace, ignore=True)
    raise TimeoutError(f"Timeout waiting for DataVolume {name} to become ready")


def _condition_status(obj, cond_type: str) -> str:
    status = obj.get("status") if hasattr(obj, "get") else getattr(obj, "status", None)
    if not status:
        return ""
    for cond in status.get("conditions") or []:
        if cond.get("type") == cond_type:
            return str(cond.get("status") or "")
    return ""


class KubeVirtStorageCheckup:
    def __init__(self, k8s: K8S, *, namespace: str, storage_class: str = DEFAULT_STORAGE_CLASS):
        self.k8s = k8s
        self.namespace = namespace
        self.storage_class = storage_class

    def run(self) -> dict:
        _print("==========================================")
        _print("KubeVirt Storage Checkup for VAST CSI")
        _print("==========================================")
        _print(f"Namespace: {self.namespace}")
        _print(f"Storage Class: {self.storage_class}")
        _print(f"Golden Image: {GOLDEN_IMAGE_NAME}")
        _print("==========================================")

        # Always clear leftovers before setup so CRC runs are not blocked by prior
        # VMs, dual-default StorageClasses, or stuck persistent-state PVCs.
        self.cleanup_previous()
        self.ensure_namespaces()
        self.ensure_kubevirt()
        self.ensure_cdi()
        self.configure_storage_profile()
        self.ensure_unique_default_storage_class()
        self.patch_empty_storage_profiles()
        self.ensure_golden_image()
        self.ensure_data_import_cron()
        self.wait_for_data_source()
        self.ensure_rbac()
        self.verify_golden_image()
        # Re-assert unique default after CSI operator may have reconciled.
        self.ensure_unique_default_storage_class()
        return self.run_checkup_job()

    def cleanup_job(self) -> None:
        _print("[INFO] Cleaning up previous test resources...")
        _safe_delete(self.k8s, "job", CHECKUP_JOB, namespace=self.namespace)
        _safe_delete(self.k8s, "configmap", CHECKUP_CONFIG, namespace=self.namespace)
        _safe_delete(self.k8s, "datavolume", "checkup-pvc", namespace=self.namespace)
        _safe_delete(self.k8s, "pvc", "checkup-pvc", namespace=self.namespace)

    def cleanup_previous(self, *, reimport_golden_image: bool = False) -> None:
        """Remove checkup leftovers. Golden images are kept unless reimport is requested."""
        _print("[INFO] Cleaning up kubevirt checkup job/VM leftovers...")
        self.cleanup_job()
        self._cleanup_test_vms()
        self._cleanup_leftover_pvcs()
        self._cleanup_prime_pvcs()
        self._drop_incomplete_clones()
        self._cleanup_legacy_golden_images()
        if not reimport_golden_image:
            _print("[INFO] Keeping existing golden image (download/convert will be skipped if already done)")
            return
        _print("[INFO] Deleting golden-image DataImportCron, DataSource, DataVolumes and PVCs...")
        _safe_delete(self.k8s, "dataimportcron", GOLDEN_IMAGE_NAME, namespace=IMAGE_NS, wait=False)
        _safe_delete(self.k8s, "datasource", GOLDEN_IMAGE_NAME, namespace=IMAGE_NS, wait=False)
        for dv in _safe_list(self.k8s, "datavolume", namespace=IMAGE_NS):
            name = str(dv.metadata.name)
            if name.startswith(GOLDEN_IMAGE_NAME):
                _safe_delete(self.k8s, "datavolume", name, namespace=IMAGE_NS, wait=False)
                _safe_delete(self.k8s, "pvc", name, namespace=IMAGE_NS, wait=False)
        self._drop_incomplete_clones()

    def _cleanup_legacy_golden_images(self) -> None:
        """Remove resources belonging to the obsolete golden image."""
        for legacy_name in LEGACY_GOLDEN_IMAGE_NAMES:
            for resource_type in ("dataimportcron", "datasource"):
                _safe_delete(
                    self.k8s,
                    resource_type,
                    legacy_name,
                    namespace=IMAGE_NS,
                    wait=False,
                )
            for resource_type in ("datavolume", "pvc"):
                for obj in _safe_list(self.k8s, resource_type, namespace=IMAGE_NS):
                    name = str(obj.metadata.name)
                    if name == legacy_name or name.startswith(f"{legacy_name}-"):
                        _safe_delete(
                            self.k8s,
                            resource_type,
                            name,
                            namespace=IMAGE_NS,
                            wait=False,
                        )

    def _cleanup_test_vms(self) -> None:
        """Delete all VMs/VMIs/DVs in the checkup namespace (incl. manual repro leftovers)."""
        _oc(
            self.k8s,
            "delete",
            "vm",
            "--all",
            "-n",
            self.namespace,
            "--ignore-not-found",
            "--wait=false",
            ignore=True,
        )
        _oc(
            self.k8s,
            "delete",
            "vmi",
            "--all",
            "-n",
            self.namespace,
            "--ignore-not-found",
            "--wait=false",
            ignore=True,
        )
        for kind in ("virtualmachinesnapshot", "virtualmachinerestore"):
            _oc(
                self.k8s,
                "delete",
                kind,
                "--all",
                "-n",
                self.namespace,
                "--ignore-not-found",
                "--wait=false",
                ignore=True,
            )
        for dv in _safe_list(self.k8s, "datavolume", namespace=self.namespace):
            name = str(dv.metadata.name)
            _safe_delete(self.k8s, "datavolume", name, namespace=self.namespace, wait=False)
            _safe_delete(self.k8s, "pvc", name, namespace=self.namespace, wait=False)

    def _cleanup_leftover_pvcs(self) -> None:
        """Remove all PVCs left in the checkup namespace (golden images live in IMAGE_NS)."""
        for pvc in self.k8s.pvcs.get(namespace=self.namespace) or []:
            name = str(pvc.metadata.name)
            _safe_delete(self.k8s, "pvc", name, namespace=self.namespace, wait=False)

    def _cleanup_prime_pvcs(self) -> None:
        for pvc in self.k8s.pvcs.get(namespace=IMAGE_NS) or []:
            name = str(pvc.metadata.name)
            if name.startswith("prime-"):
                _safe_delete(self.k8s, "pvc", name, namespace=IMAGE_NS, wait=False)

    def ensure_kubevirt(self) -> None:
        release = _kubevirt_release()
        _print(f"[INFO] KubeVirt version: {release}")

        already = _exists(self.k8s, "kubevirt", "kubevirt", namespace="kubevirt")
        if already:
            _print("[INFO] KubeVirt already deployed")
        else:
            _print("[INFO] Deploying KubeVirt operator and CR...")
            _oc(
                self.k8s,
                "apply",
                "-f",
                f"https://github.com/kubevirt/kubevirt/releases/download/{release}/kubevirt-operator.yaml",
            )
            _oc(
                self.k8s,
                "apply",
                "-f",
                f"https://github.com/kubevirt/kubevirt/releases/download/{release}/kubevirt-cr.yaml",
            )

        _print("[INFO] Granting SCC permissions to KubeVirt service accounts...")
        for sa in KUBEVIRT_SAS:
            _grant_privileged_scc(self.k8s, "kubevirt", sa)

        _print("[INFO] Waiting for KubeVirt to be available...")
        _wait_condition(self.k8s, "kubevirt", "kubevirt", namespace="kubevirt", timeout="15m")

        use_emulation = not _hardware_virtualization_available(self.k8s)
        if use_emulation:
            _print("[WARN] No KVM on any node; falling back to software emulation (slow boots)")
        else:
            _print("[INFO] KVM available; running VMs with hardware acceleration")

        _print("[INFO] Configuring KubeVirt feature gates and emulation...")
        _merge_patch(
            self.k8s,
            "kubevirt",
            "kubevirt",
            {
                "spec": {
                    "configuration": {
                        "developerConfiguration": {
                            # The checkup hotplugs by patching the VM template.
                            # KubeVirt >=1.6 requires the declarative gate for
                            # this; legacy HotplugVolumes takes precedence and
                            # leaves the running VMI unchanged.
                            "featureGates": [
                                "DataVolumes",
                                "VMPersistentState",
                                "DeclarativeHotplugVolumes",
                            ],
                            "useEmulation": use_emulation,
                        },
                        "permittedHostDevices": {"pciHostDevices": [], "mediatedDevices": []},
                    }
                }
            },
            namespace="kubevirt",
        )
        if already:
            _print("[INFO] KubeVirt already configured; leaving virt pods running")
        else:
            _print("[INFO] Restarting KubeVirt pods to apply configuration...")
            for label in KUBEVIRT_RESTART_LABELS:
                _oc(self.k8s, "delete", "pod", "-n", "kubevirt", "-l", label, "--ignore-not-found", ignore=True)

    def ensure_cdi(self) -> None:
        if _exists(self.k8s, "cdi", "cdi", namespace="cdi"):
            _print("[INFO] CDI already deployed")
        else:
            _print("[INFO] Deploying CDI operator and CR...")
            _oc(self.k8s, "apply", "-f", CDI_OPERATOR_URL)
            _oc(self.k8s, "apply", "-f", CDI_CR_URL)

        _print("[INFO] Waiting for CDI to be available...")
        _wait_condition(self.k8s, "cdi", "cdi", namespace="cdi", timeout="10m")
        _grant_privileged_scc(self.k8s, IMAGE_NS, "default")
        _grant_privileged_scc(self.k8s, "cdi", "default")

    def configure_storage_profile(self) -> None:
        _print("[INFO] Configuring storage profile for VAST CSI (cloneStrategy=snapshot)...")
        try:
            _merge_patch(
                self.k8s,
                "storageprofile",
                self.storage_class,
                {
                    "spec": {
                        "claimPropertySets": [
                            {"accessModes": ["ReadWriteMany"], "volumeMode": "Filesystem"}
                        ],
                        "cloneStrategy": "snapshot",
                    }
                },
                namespace=None,
            )
        except ProcessExecutionError as exc:
            _print(f"[WARN] Failed to patch storage profile, continuing... ({exc})")

    def ensure_unique_default_storage_class(self) -> None:
        """Ensure only the checkup StorageClass is default.

        Annotating the SC alone is not enough: VastStorage with
        setDefaultStorageClass=true will reconcile the annotation back.
        """
        _print(f"[INFO] Making StorageClass {self.storage_class} the unique cluster default...")
        for vs in _safe_list(self.k8s, "vaststorage", namespace=self.namespace):
            name = str(vs.metadata.name)
            if name == self.storage_class:
                if not bool((vs.get("spec") or {}).get("setDefaultStorageClass")):
                    _merge_patch(
                        self.k8s,
                        "vaststorage",
                        name,
                        {"spec": {"setDefaultStorageClass": True}},
                        namespace=self.namespace,
                    )
                continue
            if bool((vs.get("spec") or {}).get("setDefaultStorageClass")):
                _print(f"[INFO] Disabling setDefaultStorageClass on VastStorage/{name}")
                _merge_patch(
                    self.k8s,
                    "vaststorage",
                    name,
                    {"spec": {"setDefaultStorageClass": False}},
                    namespace=self.namespace,
                )
        _oc(
            self.k8s,
            "annotate",
            "sc",
            self.storage_class,
            f"{DEFAULT_SC_ANNOTATION}=true",
            "--overwrite",
        )
        for sc in self.k8s.storageclasses.get(namespace=None) or []:
            name = sc.metadata.name
            if name == self.storage_class:
                continue
            _oc(
                self.k8s,
                "annotate",
                "sc",
                name,
                f"{DEFAULT_SC_ANNOTATION}-",
                "--overwrite",
                ignore=True,
            )

    def patch_empty_storage_profiles(self) -> None:
        _print("[INFO] Patching StorageProfiles with empty ClaimPropertySets...")
        profiles = self.k8s.resource("storageprofile").get(namespace=None) or []
        for profile in profiles:
            name = profile.metadata.name
            if name == self.storage_class:
                continue
            claim_sets = (profile.get("status") or {}).get("claimPropertySets") or []
            if claim_sets:
                continue
            _print(f"[INFO] Patching StorageProfile: {name}")
            try:
                _merge_patch(
                    self.k8s,
                    "storageprofile",
                    name,
                    {
                        "spec": {
                            "claimPropertySets": [
                                {"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}
                            ]
                        }
                    },
                    namespace=None,
                )
            except ProcessExecutionError as exc:
                _print(f"[WARN] Failed to patch StorageProfile {name}, continuing... ({exc})")

    def ensure_namespaces(self) -> None:
        _print("[INFO] Creating namespaces if they don't exist...")
        self.k8s.namespaces.ensure(self.namespace)
        self.k8s.namespaces.ensure(IMAGE_NS)

    def _pvc_phase(self, name: str) -> str:
        pvc = _resource_or_none(self.k8s.pvcs.get(name, namespace=IMAGE_NS))
        if not pvc:
            return ""
        return str((pvc.get("status") or {}).get("phase") or "")

    def _pvc_bound(self, name: str) -> bool:
        return self._pvc_phase(name) == "Bound"

    def _dv_finished(self, name: str) -> bool:
        if self._pvc_bound(name):
            return True
        dv = self.k8s.resource("datavolume").get(name, namespace=IMAGE_NS)
        return _dv_is_ready(dv)

    def _datasource_pvc_name(self) -> str:
        ds = _resource_or_none(
            self.k8s.resource("datasource").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        if not ds:
            return ""
        return (((ds.get("spec") or {}).get("source") or {}).get("pvc") or {}).get("name") or ""

    def _hashed_bound_pvc(self) -> str:
        prefix = f"{GOLDEN_IMAGE_NAME}-"
        for pvc in self.k8s.pvcs.get(namespace=IMAGE_NS) or []:
            name = str(pvc.metadata.name)
            if name.startswith(prefix) and str((pvc.get("status") or {}).get("phase") or "") == "Bound":
                return name
        return ""

    def _datasource_ready_pvc(self) -> str:
        ds = _resource_or_none(
            self.k8s.resource("datasource").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        if not ds or _condition_status(ds, "Ready") != "True":
            return ""
        pvc_name = (((ds.get("spec") or {}).get("source") or {}).get("pvc") or {}).get("name") or ""
        if pvc_name and self._pvc_bound(pvc_name):
            return pvc_name
        return ""

    def _best_golden_pvc(self) -> str:
        """Prefer the base Alpine PVC; otherwise any Bound hashed copy."""
        if self._pvc_bound(GOLDEN_IMAGE_NAME):
            return GOLDEN_IMAGE_NAME
        return self._hashed_bound_pvc()

    def _ensure_datasource(self, pvc_name: str) -> None:
        _print(f"[INFO] Pointing DataSource {GOLDEN_IMAGE_NAME} at PVC {pvc_name}")
        _apply(self.k8s, {
            "apiVersion": "cdi.kubevirt.io/v1beta1",
            "kind": "DataSource",
            "metadata": {"name": GOLDEN_IMAGE_NAME, "namespace": IMAGE_NS},
            "spec": {"source": {"pvc": {"name": pvc_name, "namespace": IMAGE_NS}}},
        })

    def _drop_incomplete_clones(self) -> None:
        for dv in self._hashed_dvs():
            name = dv.metadata.name
            if _dv_is_ready(dv) or self._pvc_bound(name):
                continue
            _print(f"[INFO] Dropping incomplete golden-image clone {name}")
            _safe_delete(self.k8s, "datavolume", name, namespace=IMAGE_NS, wait=False)
            _safe_delete(self.k8s, "pvc", name, namespace=IMAGE_NS, wait=False)
        for pvc in self.k8s.pvcs.get(namespace=IMAGE_NS) or []:
            name = str(pvc.metadata.name)
            if name.startswith("tmp-pvc-"):
                _print(f"[INFO] Dropping leftover snapshot restore PVC {name}")
                _safe_delete(self.k8s, "pvc", name, namespace=IMAGE_NS, wait=False)
        snaps = _safe_list(self.k8s, "volumesnapshot", namespace=IMAGE_NS)
        for snap in snaps:
            name = str(snap.metadata.name)
            if name.startswith("tmp-snapshot-"):
                _print(f"[INFO] Dropping leftover snapshot {name}")
                _safe_delete(self.k8s, "volumesnapshot", name, namespace=IMAGE_NS, wait=False)

    def _checkup_golden_ready(self) -> str:
        """Ready only when DataSource is Ready and its PVC is Bound."""
        return self._datasource_ready_pvc()

    def _hashed_dvs(self):
        prefix = f"{GOLDEN_IMAGE_NAME}-"
        dvs = _safe_list(self.k8s, "datavolume", namespace=IMAGE_NS)
        hashed = [dv for dv in dvs if str(dv.metadata.name).startswith(prefix)]
        hashed.sort(key=lambda dv: dv.metadata.name, reverse=True)
        return hashed

    def _cancel_competing_dic_imports(self) -> None:
        """Drop in-progress DataImportCron copies while the HTTP image is still converting."""
        if self._pvc_bound(GOLDEN_IMAGE_NAME) or _dv_is_ready(
            self.k8s.resource("datavolume").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        ):
            return
        for dv in self._hashed_dvs():
            name = dv.metadata.name
            if self._pvc_bound(name) or _dv_is_ready(dv):
                continue
            _print(f"[INFO] Stopping extra import {name} so the HTTP convert can finish")
            _safe_delete(self.k8s, "datavolume", name, namespace=IMAGE_NS)
            _safe_delete(self.k8s, "pvc", name, namespace=IMAGE_NS)
        _safe_delete(self.k8s, "dataimportcron", GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)

    def _dic_up_to_date(self) -> bool:
        dic = _resource_or_none(
            self.k8s.resource("dataimportcron").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        return _condition_status(dic, "UpToDate") == "True"

    def _registry_source(self) -> dict:
        # Digest-pin the initial import. Do not reuse this URL on DataImportCron:
        # CDI appends @sha256 itself and a pre-pinned URL becomes invalid.
        return {"registry": {"url": f"docker://{ALPINE_IMAGE_REPO}@{ALPINE_IMAGE_DIGEST}"}}

    def _dic_source(self) -> dict:
        # Clone the already-imported Alpine PVC. Registry URLs with a digest
        # make DataImportCron emit docker://repo@sha256:...@sha256:... .
        return {"pvc": {"name": GOLDEN_IMAGE_NAME, "namespace": IMAGE_NS}}

    def _label_golden_image_pvc(self) -> None:
        if not self.k8s.pvcs.get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS):
            return
        _oc(
            self.k8s,
            "annotate",
            "pvc",
            GOLDEN_IMAGE_NAME,
            "-n",
            IMAGE_NS,
            "cdi.kubevirt.io/storage.bind.immediate.requested=true",
            "--overwrite",
            ignore=True,
        )
        _oc(
            self.k8s,
            "label",
            "pvc",
            GOLDEN_IMAGE_NAME,
            "-n",
            IMAGE_NS,
            "instancetype.kubevirt.io/default-instancetype=u1.nano",
            "instancetype.kubevirt.io/default-preference=alpine",
            "--overwrite",
            ignore=True,
        )

    def ensure_golden_image(self) -> None:
        ready_pvc = self._checkup_golden_ready()
        if ready_pvc:
            _print(f"[INFO] Golden image already converted and Bound ({ready_pvc}); skipping HTTP download/convert")
            self._label_golden_image_pvc()
            return

        self._cancel_competing_dic_imports()

        dv = self.k8s.resource("datavolume").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        if self._dv_finished(GOLDEN_IMAGE_NAME):
            _print("[INFO] Alpine golden image already imported; skipping download/convert")
            self._label_golden_image_pvc()
            return

        existing = _resource_or_none(dv) or self.k8s.pvcs.get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        if existing:
            self._label_golden_image_pvc()
            phase, download = _dv_phase_and_download(dv)
            _print(
                f"[INFO] Alpine golden image already present (phase={phase}, download={download or 'n/a'}); "
                "not re-downloading — waiting for convert/bind"
            )
            _wait_datavolume_ready(self.k8s, GOLDEN_IMAGE_NAME, IMAGE_NS)
            return

        _print("[INFO] Creating Alpine DataVolume with guest agent support...")
        _print("[INFO] This will import a ~91MB container layer / 159MiB qcow2...")
        _apply(self.k8s, {
                "apiVersion": "cdi.kubevirt.io/v1beta1",
                "kind": "DataVolume",
                "metadata": {
                    "name": GOLDEN_IMAGE_NAME,
                    "namespace": IMAGE_NS,
                    "annotations": {"cdi.kubevirt.io/storage.bind.immediate.requested": "true"},
                    "labels": {
                        "instancetype.kubevirt.io/default-instancetype": "u1.nano",
                        "instancetype.kubevirt.io/default-preference": "alpine",
                    },
                },
                "spec": {
                    "source": self._registry_source(),
                    "storage": {
                        "accessModes": ["ReadWriteMany"],
                        "resources": {"requests": {"storage": GOLDEN_IMAGE_SIZE}},
                        "storageClassName": self.storage_class,
                        "volumeMode": "Filesystem",
                    },
                },
            }
        )
        _print("[INFO] Waiting for DataVolume to be ready...")
        _wait_datavolume_ready(self.k8s, GOLDEN_IMAGE_NAME, IMAGE_NS)

    def ensure_data_import_cron(self) -> None:
        _print("[INFO] Ensuring DataImportCron so the checkup can discover the golden image...")
        existing = _resource_or_none(
            self.k8s.resource("dataimportcron").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        current_source = (
            ((((existing or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("source") or {}
        )
        if current_source.get("registry"):
            _print("[INFO] Recreating DataImportCron to clone the imported Alpine PVC")
            self.k8s.resource("dataimportcron").delete(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS, wait=False)
            time.sleep(2)
        self._drop_incomplete_clones()
        _apply(self.k8s, {
                "apiVersion": "cdi.kubevirt.io/v1beta1",
                "kind": "DataImportCron",
                "metadata": {"name": GOLDEN_IMAGE_NAME, "namespace": IMAGE_NS},
                "spec": {
                    "garbageCollect": "Outdated",
                    "importsToKeep": 1,
                    "managedDataSource": GOLDEN_IMAGE_NAME,
                    "schedule": "0 0 * * *",
                    "template": {
                        "metadata": {
                            "labels": {
                                "instancetype.kubevirt.io/default-instancetype": "u1.nano",
                                "instancetype.kubevirt.io/default-preference": "alpine",
                            }
                        },
                        "spec": {
                            "source": self._dic_source(),
                            "storage": {
                                "accessModes": ["ReadWriteMany"],
                                "resources": {"requests": {"storage": GOLDEN_IMAGE_SIZE}},
                                "storageClassName": self.storage_class,
                                "volumeMode": "Filesystem",
                            },
                        }
                    },
                },
            }
        )
        hashed_ready = [
            dv for dv in self._hashed_dvs()
            if _dv_is_ready(dv) or self._pvc_bound(dv.metadata.name)
        ]
        if hashed_ready:
            self._ensure_datasource(hashed_ready[0].metadata.name)

        if self._dic_up_to_date() and self._datasource_ready_pvc():
            _print("[INFO] DataImportCron is UpToDate and DataSource is Ready")
            return

        hashed = self._hashed_dvs()
        if hashed and (_dv_is_ready(hashed[0]) or self._pvc_bound(hashed[0].metadata.name)):
            self._ensure_datasource(hashed[0].metadata.name)

        _print("[INFO] Waiting for DataImportCron UpToDate and DataSource Ready...")
        deadline = time.time() + DV_READY_TIMEOUT_SECONDS
        latest_name = ""
        while time.time() < deadline:
            if self._dic_up_to_date() and self._datasource_ready_pvc():
                _print(f"[INFO] DataImportCron is UpToDate ({self._datasource_ready_pvc()})")
                return
            hashed = self._hashed_dvs()
            ready = [
                dv for dv in hashed
                if _dv_is_ready(dv) or self._pvc_bound(dv.metadata.name)
            ]
            if ready:
                latest_name = ready[0].metadata.name
                self._ensure_datasource(latest_name)
            elif hashed:
                latest = hashed[0]
                latest_name = latest.metadata.name
                phase, done = _print_dv_progress(self.k8s, latest_name, IMAGE_NS, latest)
                if phase == "Failed":
                    _oc(self.k8s, "describe", "datavolume", latest_name, "-n", IMAGE_NS, ignore=True)
                    raise RuntimeError(f"DataImportCron import failed with phase: {phase}")
            time.sleep(PROGRESS_INTERVAL_SECONDS)
        _print("[ERROR] Timeout waiting for DataImportCron to become UpToDate")
        _oc(self.k8s, "get", "dataimportcron", GOLDEN_IMAGE_NAME, "-n", IMAGE_NS, "-o", "yaml", ignore=True)
        _oc(self.k8s, "describe", "datasource", GOLDEN_IMAGE_NAME, "-n", IMAGE_NS, ignore=True)
        if latest_name:
            _oc(self.k8s, "describe", "datavolume", latest_name, "-n", IMAGE_NS, ignore=True)
        raise TimeoutError("Timeout waiting for DataImportCron to become UpToDate")

    def wait_for_data_source(self) -> None:
        ready_pvc = self._datasource_ready_pvc()
        if ready_pvc:
            _print(f"[INFO] DataSource is Ready and Bound ({ready_pvc})")
            return
        hashed_ready = [
            dv for dv in self._hashed_dvs()
            if _dv_is_ready(dv) or self._pvc_bound(dv.metadata.name)
        ]
        golden_pvc = hashed_ready[0].metadata.name if hashed_ready else self._best_golden_pvc()
        _print("[INFO] Verifying DataSource is ready...")
        for attempt in range(1, 31):
            if golden_pvc:
                self._ensure_datasource(golden_pvc)
            ready_pvc = self._datasource_ready_pvc()
            if ready_pvc:
                _print(f"[INFO] DataSource is Ready and Bound ({ready_pvc})")
                return
            ds = self.k8s.resource("datasource").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
            pvc_name = ""
            if ds:
                source = ((ds.get("spec") or {}).get("source") or {}).get("pvc") or {}
                pvc_name = source.get("name") or ""
            if pvc_name and self._pvc_bound(pvc_name) and _condition_status(ds, "Ready") == "True":
                _print("[INFO] DataSource is ready and references a bound PVC!")
                return
            if attempt == 30:
                _print("[ERROR] DataSource not ready after 5 minutes")
                if ds:
                    _oc(self.k8s, "describe", "datasource", GOLDEN_IMAGE_NAME, "-n", IMAGE_NS, ignore=True)
                raise TimeoutError("DataSource not ready after 5 minutes")
            time.sleep(10)

    def ensure_rbac(self) -> None:
        _print("[INFO] Creating RBAC roles for storage checkup...")
        _apply(self.k8s, [
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRole",
                    "metadata": {"name": "vm-datavolume-creator"},
                    "rules": [
                        {
                            "apiGroups": ["cdi.kubevirt.io"],
                            "resources": ["datavolumes", "datavolumes/source"],
                            "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"],
                        },
                        {
                            "apiGroups": [""],
                            "resources": ["persistentvolumeclaims"],
                            "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"],
                        },
                        {
                            "apiGroups": [""],
                            "resources": ["pods"],
                            "verbs": ["get", "list", "watch"],
                        },
                    ],
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRole",
                    "metadata": {"name": "datavolume-source-reader"},
                    "rules": [
                        {
                            "apiGroups": ["cdi.kubevirt.io"],
                            "resources": ["datavolumes/source"],
                            "verbs": ["get", "list", "watch"],
                        }
                    ],
                },
            ]
        )
        _print("[INFO] Creating service account and permissions...")
        _apply(self.k8s, [
                {
                    "apiVersion": "v1",
                    "kind": "ServiceAccount",
                    "metadata": {"name": CHECKUP_SA, "namespace": self.namespace},
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "ClusterRoleBinding",
                    "metadata": {"name": "storage-checkup-sa-cluster-admin"},
                    "subjects": [
                        {"kind": "ServiceAccount", "name": CHECKUP_SA, "namespace": self.namespace}
                    ],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": "cluster-admin",
                    },
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {"name": "datavolume-source-reader-binding", "namespace": IMAGE_NS},
                    "subjects": [
                        {"kind": "ServiceAccount", "name": CHECKUP_SA, "namespace": self.namespace}
                    ],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": "datavolume-source-reader",
                    },
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {"name": "vm-datavolume-creator-binding", "namespace": IMAGE_NS},
                    "subjects": [
                        {"kind": "ServiceAccount", "name": "default", "namespace": self.namespace}
                    ],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": "vm-datavolume-creator",
                    },
                },
                {
                    "apiVersion": "rbac.authorization.k8s.io/v1",
                    "kind": "RoleBinding",
                    "metadata": {"name": "vm-datavolume-creator-local", "namespace": self.namespace},
                    "subjects": [
                        {"kind": "ServiceAccount", "name": "default", "namespace": self.namespace}
                    ],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole",
                        "name": "vm-datavolume-creator",
                    },
                },
            ]
        )

    def inspect_golden_image(self) -> dict:
        ds = _resource_or_none(
            self.k8s.resource("datasource").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        pvc_name = ""
        if ds:
            pvc_name = (((ds.get("spec") or {}).get("source") or {}).get("pvc") or {}).get("name") or ""
        pvc = self.k8s.pvcs.get(pvc_name, namespace=IMAGE_NS) if pvc_name else None
        dic = _resource_or_none(
            self.k8s.resource("dataimportcron").get(GOLDEN_IMAGE_NAME, namespace=IMAGE_NS)
        )
        template = ((((dic or {}).get("spec") or {}).get("template") or {}).get("spec") or {})
        source = template.get("source") or {}
        storage = ((template.get("storage") or {}).get("resources") or {}).get("requests") or {}
        return {
            "datasource_present": bool(ds),
            "datasource_ready": _condition_status(ds, "Ready") if ds else "False",
            "pvc_name": pvc_name,
            "pvc_phase": str((pvc.get("status") or {}).get("phase") or "Unknown") if pvc else "Missing",
            "pvc_capacity": ((pvc.get("status") or {}).get("capacity") or {}).get("storage") if pvc else "",
            "storage_class": ((pvc.get("spec") or {}).get("storageClassName") if pvc else "") or "",
            "cron_present": bool(dic),
            "cron_up_to_date": _condition_status(dic, "UpToDate") if dic else "False",
            "cron_storage": storage.get("storage") or "",
            "cron_registry_url": ((source.get("registry") or {}).get("url") or ""),
            "cron_pvc_source": ((source.get("pvc") or {}).get("name") or ""),
        }

    def report_golden_image(self) -> bool:
        info = self.inspect_golden_image()
        _print("==========================================")
        _print("Golden Image Verification")
        _print("==========================================")
        _print("")
        _print("1. Checking active golden image PVC (from DataSource)...")
        if info["pvc_name"] and info["pvc_phase"] == "Bound":
            _print(f"   [OK] Active PVC: {info['pvc_name']}")
            _print(f"   Status: {info['pvc_phase']}")
            _print(f"   Size: {info['pvc_capacity'] or 'n/a'}")
            _print(f"   StorageClass: {info['storage_class'] or 'n/a'}")
        else:
            _print(f"   [FAIL] No Bound PVC from DataSource ({info['pvc_name'] or 'unset'}: {info['pvc_phase']})")

        _print("")
        _print("2. Checking DataSource...")
        if info["datasource_present"]:
            _print("   [OK] DataSource exists")
            _print(f"   Ready: {info['datasource_ready']}")
        else:
            _print("   [FAIL] DataSource does not exist")

        _print("")
        _print("3. Checking DataImportCron...")
        if info["cron_present"]:
            _print("   [OK] DataImportCron exists")
            _print(f"   UpToDate: {info['cron_up_to_date']}")
            _print(f"   Storage request: {info['cron_storage'] or 'n/a'}")
            source = info["cron_registry_url"] or (
                f"pvc:{info['cron_pvc_source']}" if info["cron_pvc_source"] else "n/a"
            )
            _print(f"   Source: {source}")
        else:
            _print("   [FAIL] DataImportCron does not exist")
            _print("   [WARN] kubevirt-storage-checkup requires DataImportCron to discover golden images")

        ready = (
            info["datasource_present"]
            and info["datasource_ready"] == "True"
            and info["pvc_phase"] == "Bound"
            and info["cron_present"]
            and info["cron_up_to_date"] == "True"
        )
        _print("")
        _print("==========================================")
        _print("Summary")
        _print("==========================================")
        if ready:
            _print("[OK] All components ready — golden image should be discovered")
        else:
            _print("[FAIL] Golden image will NOT be discovered by kubevirt-storage-checkup")
            _print("       Run: python3 tests/certification/redhat-e2e/run_kubevirt.py")
        return ready

    def verify_golden_image(self) -> None:
        _print("[INFO] Verifying golden image components are ready...")
        if self.report_golden_image():
            return
        info = self.inspect_golden_image()
        if info["datasource_present"]:
            _oc(self.k8s, "describe", "datasource", GOLDEN_IMAGE_NAME, "-n", IMAGE_NS, ignore=True)
        if info["pvc_name"]:
            _oc(self.k8s, "describe", "pvc", info["pvc_name"], "-n", IMAGE_NS, ignore=True)
        if info["cron_present"]:
            _oc(self.k8s, "describe", "dataimportcron", GOLDEN_IMAGE_NAME, "-n", IMAGE_NS, ignore=True)
        raise RuntimeError("Golden image components not ready")

    def run_checkup_job(self) -> dict:
        _print("[INFO] Launching KubeVirt storage checkup job...")
        _apply(self.k8s, [
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": CHECKUP_CONFIG, "namespace": self.namespace},
                    "data": {
                        "spec.timeout": CHECKUP_TIMEOUT,
                        "spec.param.storageClass": self.storage_class,
                        "spec.param.vmiTimeout": VMI_TIMEOUT,
                        "spec.param.goldenImage": GOLDEN_IMAGE_NAME,
                        "spec.param.goldenImageNamespace": IMAGE_NS,
                        "spec.param.numOfVMs": CHECKUP_NUM_VMS,
                        "spec.param.vmMemory": "512Mi",
                        "spec.param.skipTeardown": "onfailure",
                    },
                },
                {
                    "apiVersion": "batch/v1",
                    "kind": "Job",
                    "metadata": {"name": CHECKUP_JOB, "namespace": self.namespace},
                    "spec": {
                        "backoffLimit": 0,
                        "template": {
                            "spec": {
                                "serviceAccountName": CHECKUP_SA,
                                "restartPolicy": "Never",
                                "containers": [
                                    {
                                        "name": "storage-checkup",
                                        "image": CHECKUP_IMAGE,
                                        "imagePullPolicy": "Always",
                                        "env": [
                                            {"name": "CONFIGMAP_NAMESPACE", "value": self.namespace},
                                            {"name": "CONFIGMAP_NAME", "value": CHECKUP_CONFIG},
                                        ],
                                    }
                                ],
                            }
                        },
                    },
                },
            ]
        )
        _print("[INFO] Waiting for storage-checkup pod to start...")
        pod_name = None
        phase = "Unknown"
        deadline = time.time() + CHECKUP_POD_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            pods = self.k8s.pods.get(namespace=self.namespace, labels={"job-name": CHECKUP_JOB}) or []
            if pods:
                pod_name = pods[0].metadata.name
                phase = str((pods[0].get("status") or {}).get("phase") or "Unknown")
                _print(f"[INFO] Pod {pod_name} is in phase: {phase}")
                if phase in {"Running", "Succeeded", "Failed"}:
                    break
            time.sleep(1)
        else:
            raise TimeoutError(
                f"Timeout waiting for storage-checkup pod to start "
                f"(>{CHECKUP_POD_START_TIMEOUT_SECONDS}s, last phase={phase!r})"
            )

        _print("[INFO] Streaming logs from storage-checkup pod...")
        _print("==========================================")
        job_logs = ""
        try:
            job_logs = _follow_pod_logs(self.k8s, pod_name, self.namespace)
        except Exception as exc:
            _print(f"[WARN] Failed to stream checkup logs: {exc}")
        _print("==========================================")
        self._wait_checkup_finished()

        cm_yaml = _text(self.k8s.kubectl("get", "configmap", CHECKUP_CONFIG, "-n", self.namespace, "-o", "yaml"))
        _print("[INFO] Final storage checkup result:")
        if cm_yaml.strip():
            _print(cm_yaml.rstrip())
        pod = self.k8s.pods.get(pod_name, namespace=self.namespace)
        final_phase = str((pod.get("status") or {}).get("phase") or "Unknown") if pod else "Unknown"
        succeeded, detail = self.checkup_status()
        evidence = {
            "pod_name": pod_name,
            "job_logs": job_logs,
            "configmap_yaml": cm_yaml,
            "final_phase": final_phase,
            "succeeded": "true" if succeeded else "false",
        }
        if final_phase == "Failed" or not succeeded:
            _print("")
            _print("========================================")
            _print("TEST FAILED - Collecting debug info...")
            _print("========================================")
            if detail:
                _print(f"[INFO] Failure reason: {detail}")
            _oc(self.k8s, "get", "vmi,vm", "-A", ignore=True)
            _oc(self.k8s, "get", "dv", "-A", ignore=True)
            _oc(self.k8s, "get", "pods", "-n", self.namespace, "-o", "wide", ignore=True)
        return evidence

    def _wait_checkup_finished(self) -> None:
        # Outlast kiagnose's own timeout so its verdict is what we report.
        deadline = time.time() + _duration_seconds(CHECKUP_TIMEOUT) + 15 * 60
        while time.time() < deadline:
            cm = _resource_or_none(
                self.k8s.resource("configmap").get(CHECKUP_CONFIG, namespace=self.namespace)
            )
            data = (cm.get("data") or {}) if cm else {}
            if str(data.get("status.succeeded") or "").strip() in {"true", "false"}:
                return
            job = _resource_or_none(
                self.k8s.resource("job").get(CHECKUP_JOB, namespace=self.namespace)
            )
            status = (job.get("status") or {}) if job else {}
            if int(status.get("failed") or 0) > 0:
                return
            time.sleep(5)
        _print("[WARN] Timed out waiting for checkup ConfigMap status.succeeded")

    def checkup_status(self) -> tuple[bool, str]:
        cm = self.k8s.resource("configmap").get(CHECKUP_CONFIG, namespace=self.namespace)
        if not cm:
            return False, "configmap storage-checkup-config not found"
        data = cm.get("data") or {}
        value = str(data.get("status.succeeded") or "").strip()
        reason = str(data.get("status.failureReason") or "").strip()
        if value == "true":
            return True, value
        return False, reason or value or "missing status.succeeded"

    def assert_succeeded(self) -> None:
        _print("")
        _print("========================================")
        _print("Checking final test results...")
        _print("========================================")
        succeeded, detail = self.checkup_status()
        if succeeded:
            _print("")
            _print("KubeVirt storage checkup completed successfully!")
            _print(
                f"  oc get configmap {CHECKUP_CONFIG} -n {self.namespace} -o yaml > kubevirt-checkup-results.yaml"
            )
            _print("")
            return
        _print("")
        _print("KubeVirt storage checkup failed.")
        if detail:
            _print(f"Failure reason: {detail}")
        _print(f"  oc get configmap {CHECKUP_CONFIG} -n {self.namespace} -o yaml")
        _print("")
        raise RuntimeError(f"storage-checkup-config status.succeeded is not true ({detail!r})")
