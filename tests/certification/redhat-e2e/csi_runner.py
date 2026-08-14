#!/usr/bin/env python3
"""
Shared Red Hat/OpenShift CSI certification runner logic.

Supports separate NFS and block profiles with isolated output folders:
  output/nfs/<timestamp>/
  output/block/<timestamp>/
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Optional

DEFAULT_IMAGE = "registry.redhat.io/openshift4/ose-tests"
DEFAULT_SUITE = "openshift/csi"
DEFAULT_VAST_USERNAME = "admin"
DEFAULT_VAST_PASSWORD = "123456"
NFS_VOLUME_NAME_FORMAT = "csi:{id}"
NFS_MOUNT_OPTIONS = ("vers=4.1",)
# Wait for GSS clone completion before returning from volume clone (required for certification).
BLOCKING_CLONES = True
SNAPSHOT_CRDS_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install_snapshot_crds.sh"
SNAPSHOT_CLASS_CRD = "volumesnapshotclasses.snapshot.storage.k8s.io"


def _yaml_string(value: str) -> str:
    """Return a YAML-safe quoted string (avoids numeric passwords becoming integers)."""
    return json.dumps(value)


def _resolve_vast_endpoint(cfg: RunnerConfig) -> str:
    endpoint = cfg.vast_endpoint or _existing_cluster_endpoint(cfg)
    if not endpoint:
        raise RuntimeError(
            "Missing VAST endpoint for block subsystem setup.\n"
            "Pass --vast-endpoint <ip-or-fqdn> or set VAST_ENDPOINT."
        )
    return endpoint


def _vast_api_request(
    cfg: RunnerConfig,
    method: str,
    resource: str,
    *,
    endpoint: str,
    params: Optional[dict[str, str]] = None,
    data: Optional[dict[str, object]] = None,
) -> object:
    url = f"https://{endpoint}/api/{resource.strip('/')}/"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "content-type": "application/json",
        "authorization": "Basic "
        + base64.b64encode(f"{cfg.vast_username}:{cfg.vast_password}".encode()).decode(),
    }
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, context=context, timeout=60) as response:
            raw = response.read().decode()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        details = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"VAST API {method.upper()} {url} failed with HTTP {exc.code}.\n{details}"
        ) from exc


def ensure_block_subsystem(cfg: RunnerConfig) -> None:
    """Create NVMe-oF block subsystem (view) on VAST"""
    if cfg.profile != "block" or not cfg.vast_subsystem:
        return

    endpoint = _resolve_vast_endpoint(cfg)
    subsystem = cfg.vast_subsystem
    path = f"/{subsystem}"
    print(f"Ensuring VAST block subsystem {subsystem!r} at path {path!r} on {endpoint}...")

    existing = _vast_api_request(
        cfg,
        "GET",
        "views",
        endpoint=endpoint,
        params={"name": subsystem},
    )
    if isinstance(existing, list):
        for view in existing:
            protocols = view.get("protocols") or []
            if "BLOCK" in protocols and view.get("name") == subsystem:
                print(f"VAST block subsystem {subsystem!r} already exists.")
                return

    policies = _vast_api_request(
        cfg,
        "GET",
        "viewpolicies",
        endpoint=endpoint,
        params={"name": cfg.vast_view_policy},
    )
    if not isinstance(policies, list) or not policies:
        raise RuntimeError(
            f"View policy {cfg.vast_view_policy!r} not found on VAST cluster {endpoint}."
        )

    _vast_api_request(
        cfg,
        "POST",
        "views",
        endpoint=endpoint,
        data={
            "path": path,
            "name": subsystem,
            "create_dir": True,
            "protocols": ["BLOCK"],
            "policy_id": policies[0]["id"],
        },
    )
    print(f"Created VAST block subsystem {subsystem!r} at path {path!r}.")


def _policy_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def ensure_nfs_view_policy(cfg: RunnerConfig) -> None:
    """Clear nfs_root_squash and allow nfs_no_squash=* on the NFS view policy.

    Matches Orion test_operator_e2e_filesystem so KubeVirt/CSI can chown on NFS
    (root_squash would return EPERM).
    """
    if cfg.profile != "nfs":
        return

    endpoint = _resolve_vast_endpoint(cfg)
    policy_name = cfg.vast_view_policy
    print(f"Ensuring view policy {policy_name!r} has nfs_root_squash=[] and nfs_no_squash=['*'] on {endpoint}...")

    policies = _vast_api_request(
        cfg,
        "GET",
        "viewpolicies",
        endpoint=endpoint,
        params={"name": policy_name},
    )
    if not isinstance(policies, list) or not policies:
        raise RuntimeError(f"View policy {policy_name!r} not found on VAST cluster {endpoint}.")

    policy = policies[0]
    policy_id = policy.get("id")
    if policy_id is None:
        raise RuntimeError(f"View policy {policy_name!r} has no id.")

    desired_root: list[str] = []
    desired_no = ["*"]
    desired_auth = False
    current_root = _policy_list(policy.get("nfs_root_squash"))
    current_no = _policy_list(policy.get("nfs_no_squash"))
    current_auth = policy.get("use_auth_provider")
    if current_root == desired_root and current_no == desired_no and current_auth is desired_auth:
        print(f"View policy {policy_name!r} already has no root squash.")
        return

    _vast_api_request(
        cfg,
        "PATCH",
        f"viewpolicies/{policy_id}",
        endpoint=endpoint,
        data={
            "nfs_root_squash": desired_root,
            "nfs_no_squash": desired_no,
            "use_auth_provider": desired_auth,
        },
    )
    print(
        f"Updated view policy {policy_name!r}: "
        f"nfs_root_squash {current_root} -> {desired_root}, "
        f"nfs_no_squash {current_no} -> {desired_no}."
    )


NFS_KEYWORDS = (
    "dynamic provisioning",
    "persistence",
    "controller expansion",
    "snapshot",
)
NFS_SKIP_PATTERNS = (
    "block",
    "topology",
    "volume limits",
    "node expansion",
    "single node volume",
    "[feature:windows]",
    "(ntfs)",
    "(xfs)",
    "[slow]",
    "ephemeral-volume",
    "mount options",
)

BLOCK_KEYWORDS = (
    "block volmode",
    "persistence",
    "should store data",
    "volumemode",
)
BLOCK_SKIP_PATTERNS = (
    "topology",
    "volume limits",
    "node expansion",
    "single node volume",
    "[feature:windows]",
    "[slow]",
    "ephemeral-volume",
    "mount options",
    "snapshot",
    "clone",
    "rox mode",
    "volume-expand",
    "allowexpansion",
    "fsgroup",
    "pvc data source",
    "capacity",
    "(default fs)",
)


@dataclass(frozen=True)
class ProfileDefaults:
    name: str
    manifest: str
    output_subdir: str
    keywords: tuple[str, ...]
    skip_patterns: tuple[str, ...]
    vast_cluster_name: str
    vast_storage_name: str
    vast_csi_driver_name: str
    driver_type: str
    provisioner: str
    vast_subsystem: Optional[str] = None
    volume_name_format: Optional[str] = None


PROFILES: dict[str, ProfileDefaults] = {
    "nfs": ProfileDefaults(
        name="nfs",
        manifest="manifest-nfs.yaml",
        output_subdir="nfs",
        keywords=NFS_KEYWORDS,
        skip_patterns=NFS_SKIP_PATTERNS,
        vast_cluster_name="cluster",
        vast_storage_name="vastdata-filesystem",
        vast_csi_driver_name="csi.vastdata.com",
        driver_type="nfs",
        provisioner="csi.vastdata.com",
        volume_name_format=NFS_VOLUME_NAME_FORMAT,
    ),
    "block": ProfileDefaults(
        name="block",
        manifest="manifest-block.yaml",
        output_subdir="block",
        keywords=BLOCK_KEYWORDS,
        skip_patterns=BLOCK_SKIP_PATTERNS,
        vast_cluster_name="cluster-block",
        vast_storage_name="vastdata-block",
        vast_csi_driver_name="block.csi.vastdata.com",
        driver_type="block",
        provisioner="block.csi.vastdata.com",
        vast_subsystem="redhat-e2e-block",
    ),
}


@dataclass(frozen=True)
class RunnerConfig:
    profile: str
    work_dir: Path
    kubeconfig: Path
    oc_bin: Optional[str]
    manifest: Path
    output_dir: Path
    image: str
    suite: str
    keywords: tuple[str, ...]
    skip_patterns: tuple[str, ...]
    max_tests: int
    list_only: bool
    ensure_csi_resources: bool
    csi_namespace: str
    vast_endpoint: Optional[str]
    vast_username: str
    vast_password: str
    vast_cluster_name: str
    vast_storage_name: str
    vast_csi_driver_name: str
    vast_vip_pool: str
    vast_view_policy: str
    driver_type: str
    provisioner: str
    vast_subsystem: Optional[str]
    vast_volume_name_format: Optional[str]


def _run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    kwargs: dict[str, object] = {"check": check, "text": True}
    if capture:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.STDOUT
    return subprocess.run(cmd, **kwargs)


def _resolve_oc_binary() -> Optional[str]:
    detected = shutil.which("oc")
    if detected:
        return detected

    candidates = (
        Path.home() / ".crc/bin/oc/oc",
        Path.home() / ".crc/bin/oc",
        Path("/usr/local/bin/oc"),
        Path("/usr/bin/oc"),
    )
    for path in candidates:
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            return str(path)

    return None


def _can_execute_oc(oc_bin: Optional[str], kubeconfig: Path) -> bool:
    if not oc_bin:
        return False
    try:
        subprocess.run(
            [oc_bin, "--kubeconfig", str(kubeconfig), "whoami"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return True
    except (subprocess.CalledProcessError, PermissionError, OSError):
        return False


def _docker_base_cmd(cfg: RunnerConfig) -> list[str]:
    return [
        "docker",
        "run",
        "--network",
        "host",
        "--rm",
        "-i",
        "-v",
        f"{cfg.work_dir}:/suite",
        "-v",
        f"{cfg.kubeconfig}:/kubeconfig:ro",
        cfg.image,
    ]


def _parse_tests(output: str) -> list[str]:
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    lines = [ansi.sub("", line).strip() for line in output.splitlines()]
    tests: list[str] = []
    for line in lines:
        if not line:
            continue
        if line.startswith('"') and line.endswith('"') and "Driver:" in line:
            tests.append(line.strip('"'))
            continue
        if line.startswith("[") and "]" in line:
            tests.append(line)
            continue
        if "openshift/csi" in line and "[" in line and "]" in line:
            tests.append(line)
            continue
        if line.startswith("test/e2e/") and ("csi" in line.lower() or "storage" in line.lower()):
            tests.append(line)
    seen = set()
    unique: list[str] = []
    for test in tests:
        if test not in seen:
            seen.add(test)
            unique.append(test)
    return unique


def _contains_any(text: str, words: Iterable[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def select_tests(candidates: list[str], keywords: tuple[str, ...], skip_patterns: tuple[str, ...], max_tests: int) -> list[str]:
    filtered = [
        test
        for test in candidates
        if _contains_any(test, keywords) and not _contains_any(test, skip_patterns)
    ]
    return filtered[:max_tests]


def _discover_once(cfg: RunnerConfig, with_manifest: bool, suite: Optional[str] = None) -> tuple[list[str], str]:
    suite_name = suite or cfg.suite
    manifest_name = cfg.manifest.name
    if with_manifest:
        shell_cmd = (
            "KUBECONFIG=/kubeconfig "
            f"TEST_CSI_DRIVER_FILES=/suite/{manifest_name} "
            f"/usr/bin/openshift-tests run {shlex.quote(suite_name)} --dry-run"
        )
    else:
        shell_cmd = (
            "KUBECONFIG=/kubeconfig "
            f"/usr/bin/openshift-tests run {shlex.quote(suite_name)} --dry-run"
        )
    cmd = _docker_base_cmd(cfg) + ["sh", "-c", shell_cmd]
    completed = _run(cmd, capture=True, check=False)
    out = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(
            "Failed to discover tests via openshift-tests dry-run.\n"
            f"Exit code: {completed.returncode}\n"
            "Command output:\n"
            f"{out}"
        )
    return _parse_tests(out), out


def discover_tests(cfg: RunnerConfig) -> list[str]:
    candidates, output = _discover_once(cfg, with_manifest=True)
    (cfg.output_dir / "discovery.with-manifest.log").write_text(output, encoding="utf-8")
    if candidates:
        return candidates

    candidates_all, output_all = _discover_once(cfg, with_manifest=False, suite="all")
    (cfg.output_dir / "discovery.all.log").write_text(output_all, encoding="utf-8")
    csi_candidates = [candidate for candidate in candidates_all if ("csi" in candidate.lower() or "storage" in candidate.lower())]
    if csi_candidates:
        return csi_candidates

    try:
        candidates, output = _discover_once(cfg, with_manifest=False)
        (cfg.output_dir / "discovery.no-manifest.log").write_text(output, encoding="utf-8")
        return candidates
    except RuntimeError as exc:
        (cfg.output_dir / "discovery.no-manifest.log").write_text(str(exc), encoding="utf-8")
        return []


def run_test_case(cfg: RunnerConfig, test_name: str, test_index: int) -> tuple[int, str]:
    log_path = cfg.output_dir / "logs" / f"test-{test_index:02d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = _docker_base_cmd(cfg) + [
        "sh",
        "-c",
        (
            "KUBECONFIG=/kubeconfig "
            f"TEST_CSI_DRIVER_FILES=/suite/{cfg.manifest.name} "
            f"/usr/bin/openshift-tests run-test {shlex.quote(test_name)}"
        ),
    ]
    proc = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = proc.stdout or ""
    log_path.write_text(output, encoding="utf-8")

    if proc.returncode == 3 and ("[SKIPPED]" in output or "skip [" in output):
        return proc.returncode, "skipped"
    if proc.returncode == 0:
        return proc.returncode, "passed"
    return proc.returncode, "failed"


def collect_cluster_metadata(cfg: RunnerConfig) -> None:
    if not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        print("Skipping cluster metadata collection: oc is unavailable or not executable.")
        return

    meta_dir = cfg.output_dir / "cluster-metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    commands = {
        "clusterversion.yaml": [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "get", "clusterversion", "-o", "yaml"],
        "nodes.yaml": [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "get", "nodes", "-o", "yaml"],
        "storageclasses.yaml": [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "get", "sc", "-o", "yaml"],
        "snapshotclasses.yaml": [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "get", "volumesnapshotclass", "-o", "yaml"],
    }
    for filename, cmd in commands.items():
        result = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (meta_dir / filename).write_text(result.stdout or "", encoding="utf-8")


def _existing_cluster_endpoint(cfg: RunnerConfig) -> Optional[str]:
    if not cfg.oc_bin:
        return None
    cluster_names = [cfg.vast_cluster_name]
    existing_cluster = _existing_storage_cluster_name(cfg)
    if existing_cluster and existing_cluster not in cluster_names:
        cluster_names.append(existing_cluster)
    for cluster_name in cluster_names:
        probe = subprocess.run(
            [
                cfg.oc_bin,
                "--kubeconfig",
                str(cfg.kubeconfig),
                "-n",
                cfg.csi_namespace,
                "get",
                "vastcluster",
                cluster_name,
                "-o",
                "jsonpath={.spec.endpoint}",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if probe.returncode == 0 and (probe.stdout or "").strip():
            return probe.stdout.strip()
    return None


def _existing_storage_cluster_name(cfg: RunnerConfig) -> Optional[str]:
    if not cfg.oc_bin:
        return None
    probe = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "get",
            "vaststorage",
            cfg.vast_storage_name,
            "-o",
            "jsonpath={.spec.clusterName}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if probe.returncode == 0 and (probe.stdout or "").strip():
        return probe.stdout.strip()
    return None


def _resolve_vast_cluster_name(cfg: RunnerConfig) -> str:
    return _existing_storage_cluster_name(cfg) or cfg.vast_cluster_name


def _snapshot_crds_installed(cfg: RunnerConfig) -> bool:
    if not cfg.oc_bin:
        return False
    probe = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "get",
            "crd",
            SNAPSHOT_CLASS_CRD,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return probe.returncode == 0


def _wait_for_snapshot_crds(cfg: RunnerConfig, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _snapshot_crds_installed(cfg):
            established = subprocess.run(
                [
                    cfg.oc_bin,
                    "--kubeconfig",
                    str(cfg.kubeconfig),
                    "get",
                    "crd",
                    SNAPSHOT_CLASS_CRD,
                    "-o",
                    "jsonpath={.status.conditions[?(@.type==\"Established\")].status}",
                ],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            if (established.stdout or "").strip() == "True":
                return
        time.sleep(2)
    raise RuntimeError(
        f"Timed out waiting for CRD {SNAPSHOT_CLASS_CRD} to become Established."
    )


def _reset_failed_vaststorage(cfg: RunnerConfig) -> None:
    """Delete VastStorage stuck in ReleaseFailed so Helm retries after snapshot CRDs exist."""
    if not cfg.oc_bin:
        return
    probe = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "get",
            "vaststorage",
            cfg.vast_storage_name,
            "-o",
            "json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if probe.returncode != 0 or not (probe.stdout or "").strip().startswith("{"):
        return
    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError:
        return
    failed = any(
        cond.get("type") == "ReleaseFailed" and str(cond.get("status")) == "True"
        for cond in (payload.get("status") or {}).get("conditions") or []
    )
    if not failed:
        return
    print(
        f"VastStorage/{cfg.vast_storage_name} is ReleaseFailed; "
        "deleting so Helm can retry after snapshot CRDs are installed..."
    )
    subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "delete",
            "vaststorage",
            cfg.vast_storage_name,
            "--wait=true",
            "--ignore-not-found",
        ],
        check=False,
        text=True,
    )


def ensure_snapshot_crds(cfg: RunnerConfig) -> None:
    """Install VolumeSnapshot CRDs and snapshot-controller when missing (CRC/local clusters)."""
    if not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        print("Skipping snapshot CRD install: oc is unavailable or not executable.")
        return

    if _snapshot_crds_installed(cfg):
        print("VolumeSnapshot CRDs already installed.")
        _reset_failed_vaststorage(cfg)
        return

    if not SNAPSHOT_CRDS_SCRIPT.is_file():
        raise FileNotFoundError(f"Missing snapshot CRD installer: {SNAPSHOT_CRDS_SCRIPT}")

    print(f"Installing VolumeSnapshot CRDs via {SNAPSHOT_CRDS_SCRIPT} ...")
    env = os.environ.copy()
    env["KUBECONFIG"] = str(cfg.kubeconfig)
    result = subprocess.run(
        ["bash", str(SNAPSHOT_CRDS_SCRIPT)],
        check=False,
        text=True,
        env=env,
    )
    if result.returncode != 0 and not _snapshot_crds_installed(cfg):
        raise RuntimeError(
            f"{SNAPSHOT_CRDS_SCRIPT} failed with exit code {result.returncode} "
            "and VolumeSnapshot CRDs are still missing."
        )
    if result.returncode != 0:
        print(
            f"Warning: {SNAPSHOT_CRDS_SCRIPT.name} exited {result.returncode}, "
            "but VolumeSnapshot CRDs are present; continuing."
        )

    _wait_for_snapshot_crds(cfg)
    print("VolumeSnapshot CRDs are installed.")
    _reset_failed_vaststorage(cfg)


def ensure_csi_resources(cfg: RunnerConfig) -> None:
    if not cfg.ensure_csi_resources:
        return
    if not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        raise RuntimeError(
            "Cannot ensure CSI resources automatically because 'oc' is unavailable.\n"
            "Either fix oc permissions/path or use --skip-ensure-csi-resources."
        )

    endpoint = cfg.vast_endpoint or _existing_cluster_endpoint(cfg)
    if endpoint:
        print(f"Using VastCluster endpoint: {endpoint}")
    else:
        raise RuntimeError(
            "Missing VAST endpoint for automatic resource setup.\n"
            "Pass --vast-endpoint <ip-or-fqdn> or set VAST_ENDPOINT."
        )

    ns_manifest = dedent(
        f"""\
        apiVersion: v1
        kind: Namespace
        metadata:
          name: {cfg.csi_namespace}
        """
    )
    subprocess.run(
        [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "apply", "-f", "-"],
        input=ns_manifest,
        check=True,
        text=True,
    )

    if cfg.profile == "block":
        crs_manifest = dedent(
            f"""\
            apiVersion: storage.vastdata.com/v1
            kind: VastCluster
            metadata:
              name: {cfg.vast_cluster_name}
              namespace: {cfg.csi_namespace}
            spec:
              endpoint: {endpoint}
              username: {_yaml_string(cfg.vast_username)}
              password: {_yaml_string(cfg.vast_password)}
            ---
            apiVersion: storage.vastdata.com/v1
            kind: VastStorage
            metadata:
              name: {cfg.vast_storage_name}
              namespace: {cfg.csi_namespace}
            spec:
              driverType: {cfg.driver_type}
              provisioner: {cfg.provisioner}
              clusterName: {cfg.vast_cluster_name}
              subsystem: {cfg.vast_subsystem}
              vipPool: {cfg.vast_vip_pool}
              blockingClones: {str(BLOCKING_CLONES).lower()}
              createSnapshotClass: true
            ---
            apiVersion: storage.vastdata.com/v1
            kind: VastCSIDriver
            metadata:
              name: {cfg.vast_csi_driver_name}
              namespace: {cfg.csi_namespace}
            spec:
              driverType: {cfg.driver_type}
            """
        )
    else:
        cluster_name = _resolve_vast_cluster_name(cfg)
        volume_name_format_line = ""
        if cfg.vast_volume_name_format:
            volume_name_format_line = (
                f"              volumeNameFormat: {cfg.vast_volume_name_format}\n"
                f"              ephemeralVolumeNameFormat: {cfg.vast_volume_name_format}\n"
                f"              snapshotClass:\n"
                f"                snapshotNameFormat: {cfg.vast_volume_name_format}\n"
            )
        mount_options_lines = "".join(f"                - {opt}\n" for opt in NFS_MOUNT_OPTIONS)
        crs_manifest = dedent(
            f"""\
            apiVersion: storage.vastdata.com/v1
            kind: VastCluster
            metadata:
              name: {cluster_name}
              namespace: {cfg.csi_namespace}
            spec:
              endpoint: {endpoint}
              username: {_yaml_string(cfg.vast_username)}
              password: {_yaml_string(cfg.vast_password)}
            ---
            apiVersion: storage.vastdata.com/v1
            kind: VastStorage
            metadata:
              name: {cfg.vast_storage_name}
              namespace: {cfg.csi_namespace}
            spec:
              clusterName: {cluster_name}
              provisioner: {cfg.provisioner}
              storagePath: /k8s
              vipPool: {cfg.vast_vip_pool}
              viewPolicy: {cfg.vast_view_policy}
              mountOptions:
{mount_options_lines}{volume_name_format_line}              blockingClones: {str(BLOCKING_CLONES).lower()}
              createSnapshotClass: true
            ---
            apiVersion: storage.vastdata.com/v1
            kind: VastCSIDriver
            metadata:
              name: {cfg.vast_csi_driver_name}
              namespace: {cfg.csi_namespace}
            spec: {{}}
            """
        )
    subprocess.run(
        [cfg.oc_bin, "--kubeconfig", str(cfg.kubeconfig), "apply", "-f", "-"],
        input=crs_manifest,
        check=True,
        text=True,
    )


def _vsc_snapshot_name_fmt(cfg: RunnerConfig, vsc_name: str) -> Optional[str]:
    if not cfg.oc_bin:
        return None
    probe = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "get",
            "volumesnapshotclass",
            vsc_name,
            "-o",
            "jsonpath={.parameters.snapshot_name_fmt}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if probe.returncode != 0:
        return None
    return (probe.stdout or "").strip() or None


def ensure_blocking_clones(cfg: RunnerConfig) -> None:
    """Ensure VastStorage blockingClones is enabled so clone ops wait for GSS completion."""
    if not BLOCKING_CLONES or not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        return

    probe = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "get",
            "vaststorage",
            cfg.vast_storage_name,
            "-o",
            "jsonpath={.spec.blockingClones}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if probe.returncode != 0:
        print(
            f"VastStorage/{cfg.vast_storage_name} not found; "
            f"operator will create it with blockingClones=true."
        )
        return

    current = (probe.stdout or "").strip().lower()
    if current == "true":
        return

    print(f"Patching VastStorage/{cfg.vast_storage_name} blockingClones=true ...")
    subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "patch",
            "vaststorage",
            cfg.vast_storage_name,
            "--type=merge",
            "-p",
            '{"spec":{"blockingClones":true}}',
        ],
        check=True,
        text=True,
    )


def ensure_volume_snapshot_class_format(cfg: RunnerConfig, timeout_seconds: int = 120) -> None:
    """Recreate VolumeSnapshotClass when snapshot_name_fmt is wrong (parameter is immutable)."""
    if not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        return
    expected = cfg.vast_volume_name_format
    if not expected:
        return

    vsc_name = cfg.vast_storage_name
    current = _vsc_snapshot_name_fmt(cfg, vsc_name)
    if current == expected:
        print(f"VolumeSnapshotClass/{vsc_name} snapshot_name_fmt is already {expected!r}.")
        return
    if current is None:
        print(f"VolumeSnapshotClass/{vsc_name} not found; operator will create it.")
        return

    print(
        f"VolumeSnapshotClass/{vsc_name} has snapshot_name_fmt={current!r}, "
        f"expected {expected!r}. Deleting stuck snapshots and recreating class..."
    )

    snapshots = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "get",
            "volumesnapshot",
            "-A",
            "-o",
            "json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if snapshots.returncode == 0 and snapshots.stdout:
        payload = json.loads(snapshots.stdout)
        for item in payload.get("items", []):
            if item.get("spec", {}).get("volumeSnapshotClassName") != vsc_name:
                continue
            ns = item["metadata"]["namespace"]
            name = item["metadata"]["name"]
            print(f"  Deleting VolumeSnapshot/{ns}/{name} ...")
            subprocess.run(
                [
                    cfg.oc_bin,
                    "--kubeconfig",
                    str(cfg.kubeconfig),
                    "-n",
                    ns,
                    "delete",
                    "volumesnapshot",
                    name,
                    "--ignore-not-found",
                    "--wait=false",
                ],
                check=False,
                text=True,
            )

    subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "delete",
            "volumesnapshotclass",
            vsc_name,
            "--ignore-not-found",
            "--wait=true",
        ],
        check=True,
        text=True,
    )

    # Helm operator watches VolumeSnapshotClass as primary resource; nudge reconcile via annotation.
    subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "annotate",
            "vaststorage",
            cfg.vast_storage_name,
            f"certification/reconcile={int(time.time())}",
            "--overwrite",
        ],
        check=False,
        text=True,
    )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        recreated = _vsc_snapshot_name_fmt(cfg, vsc_name)
        if recreated == expected:
            print(f"VolumeSnapshotClass/{vsc_name} recreated with snapshot_name_fmt={expected!r}.")
            return
        time.sleep(3)

    raise RuntimeError(
        f"Timed out waiting for VolumeSnapshotClass/{vsc_name} to be recreated "
        f"with snapshot_name_fmt={expected!r}."
    )


def wait_for_csi_ready(cfg: RunnerConfig, timeout_seconds: int = 300) -> None:
    if not cfg.oc_bin or not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        print("Skipping CSI readiness wait: oc is unavailable or not executable.")
        return

    storage_class = cfg.vast_storage_name
    print(
        f"Waiting for StorageClass {storage_class!r} and VastStorage/{cfg.vast_storage_name} deployment..."
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        sc = subprocess.run(
            [
                cfg.oc_bin,
                "--kubeconfig",
                str(cfg.kubeconfig),
                "get",
                "storageclass",
                storage_class,
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deployed = subprocess.run(
            [
                cfg.oc_bin,
                "--kubeconfig",
                str(cfg.kubeconfig),
                "-n",
                cfg.csi_namespace,
                "get",
                "vaststorage",
                cfg.vast_storage_name,
                "-o",
                "jsonpath={.status.conditions[?(@.type==\"Deployed\")].status}",
            ],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if sc.returncode == 0 and (deployed.stdout or "").strip() == "True":
            print(f"CSI resources ready: StorageClass/{storage_class} exists and VastStorage is deployed.")
            return

        time.sleep(5)

    status = subprocess.run(
        [
            cfg.oc_bin,
            "--kubeconfig",
            str(cfg.kubeconfig),
            "-n",
            cfg.csi_namespace,
            "get",
            "vaststorage",
            cfg.vast_storage_name,
            "-o",
            "yaml",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    raise RuntimeError(
        f"Timed out after {timeout_seconds}s waiting for block/NFS CSI resources.\n"
        f"Expected StorageClass/{storage_class} and VastStorage/{cfg.vast_storage_name} (Deployed=True).\n"
        "Check operator logs:\n"
        f"  oc -n {cfg.csi_namespace} get vaststorage,vastcluster,vastcsidriver\n"
        f"  oc get sc {storage_class}\n"
        f"VastStorage status:\n{status.stdout or ''}"
    )


def save_summary(cfg: RunnerConfig, selected: list[str], results: list[dict[str, object]]) -> None:
    payload = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "profile": cfg.profile,
        "suite": cfg.suite,
        "selected_tests": selected,
        "results": results,
        "environment": {
            "kubeconfig": str(cfg.kubeconfig),
            "manifest": str(cfg.manifest),
            "image": cfg.image,
        },
    }
    (cfg.output_dir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    shutil.copy2(cfg.manifest, cfg.output_dir / cfg.manifest.name)


def create_archive(cfg: RunnerConfig) -> Path:
    archive = cfg.output_dir.parent / f"{cfg.output_dir.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(cfg.output_dir, arcname=f"{cfg.profile}/{cfg.output_dir.name}")
    return archive


def validate_prerequisites(cfg: RunnerConfig) -> None:
    for path in (cfg.kubeconfig, cfg.manifest):
        if not path.exists():
            raise FileNotFoundError(f"Required file does not exist: {path}")

    _run(["docker", "version"], check=True)
    if cfg.oc_bin and not _can_execute_oc(cfg.oc_bin, cfg.kubeconfig):
        print(
            "Warning: detected oc binary is not executable. "
            "Suite will continue without oc-based metadata collection."
        )

    inspect = _run(["docker", "image", "inspect", cfg.image], check=False, capture=True)
    if inspect.returncode != 0:
        pull = _run(["docker", "pull", cfg.image], check=False, capture=True)
        if pull.returncode != 0:
            output = pull.stdout or ""
            if "Please login to the Red Hat Registry" in output or "unauthorized" in output.lower():
                raise RuntimeError(
                    "Cannot pull certification image from registry.redhat.io.\n"
                    "Authenticate Docker first, then rerun:\n\n"
                    "  docker login registry.redhat.io\n\n"
                    "Use your Red Hat Customer Portal username and password/token.\n"
                    "If your account uses SSO/token flow, see:\n"
                    "https://access.redhat.com/RegistryAuthentication\n\n"
                    f"Raw docker output:\n{output}"
                )
            raise RuntimeError(
                "Cannot pull certification image.\n"
                f"Image: {cfg.image}\n"
                "Raw docker output:\n"
                f"{output}"
            )


def build_ensure_config(
    profile_name: str,
    *,
    kubeconfig: Path,
    vast_endpoint: Optional[str] = None,
    csi_namespace: str = "vast-csi",
    vast_subsystem: Optional[str] = None,
    vast_username: str = DEFAULT_VAST_USERNAME,
    vast_password: str = DEFAULT_VAST_PASSWORD,
) -> RunnerConfig:
    """Build a RunnerConfig for idempotent VAST CR setup (NFS CSI or KubeVirt)."""
    profile = PROFILES[profile_name]
    work_dir = Path(__file__).resolve().parent
    return RunnerConfig(
        profile=profile.name,
        work_dir=work_dir,
        kubeconfig=kubeconfig,
        oc_bin=_resolve_oc_binary(),
        manifest=work_dir / profile.manifest,
        output_dir=work_dir / "output" / profile.output_subdir / ".ensure",
        image=DEFAULT_IMAGE,
        suite=DEFAULT_SUITE,
        keywords=profile.keywords,
        skip_patterns=profile.skip_patterns,
        max_tests=0,
        list_only=False,
        ensure_csi_resources=True,
        csi_namespace=csi_namespace,
        vast_endpoint=vast_endpoint,
        vast_username=vast_username,
        vast_password=vast_password,
        vast_cluster_name=profile.vast_cluster_name,
        vast_storage_name=profile.vast_storage_name,
        vast_csi_driver_name=profile.vast_csi_driver_name,
        vast_vip_pool="vippool-1",
        vast_view_policy="default",
        driver_type=profile.driver_type,
        provisioner=profile.provisioner,
        vast_subsystem=vast_subsystem or profile.vast_subsystem,
        vast_volume_name_format=profile.volume_name_format,
    )


def ensure_profile_stack(
    profile_name: str,
    *,
    kubeconfig: Path,
    vast_endpoint: Optional[str] = None,
    csi_namespace: str = "vast-csi",
    vast_subsystem: Optional[str] = None,
    skip: bool = False,
) -> None:
    """Ensure VAST CSI CRs for a profile exist (safe to call from NFS CSI or KubeVirt)."""
    if skip:
        return
    cfg = build_ensure_config(
        profile_name,
        kubeconfig=kubeconfig,
        vast_endpoint=vast_endpoint,
        csi_namespace=csi_namespace,
        vast_subsystem=vast_subsystem,
    )
    if profile_name == "block":
        ensure_block_subsystem(cfg)
    if profile_name == "nfs":
        ensure_nfs_view_policy(cfg)
    ensure_snapshot_crds(cfg)
    ensure_csi_resources(cfg)
    ensure_blocking_clones(cfg)
    ensure_volume_snapshot_class_format(cfg)
    wait_for_csi_ready(cfg)


def prepare_output_dir(work_dir: Path, profile: ProfileDefaults, explicit_output: Optional[str]) -> Path:
    output_root = work_dir / "output" / profile.output_subdir
    output_root.mkdir(parents=True, exist_ok=True)
    for item in output_root.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)

    output_dir = Path(explicit_output) if explicit_output else output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def build_config(args) -> RunnerConfig:
    work_dir = Path(__file__).resolve().parent
    profile = PROFILES[args.profile]
    output_dir = prepare_output_dir(work_dir, profile, args.output_dir)

    return RunnerConfig(
        profile=profile.name,
        work_dir=work_dir,
        kubeconfig=Path(args.kubeconfig).expanduser().resolve(),
        oc_bin=_resolve_oc_binary(),
        manifest=Path(args.manifest).expanduser().resolve(),
        output_dir=output_dir,
        image=args.image,
        suite=args.suite,
        keywords=tuple(args.keyword) if args.keyword else profile.keywords,
        skip_patterns=tuple(args.skip_pattern) if args.skip_pattern else profile.skip_patterns,
        max_tests=args.max_tests,
        list_only=args.list_only,
        ensure_csi_resources=not args.skip_ensure_csi_resources,
        csi_namespace=args.csi_namespace,
        vast_endpoint=args.vast_endpoint,
        vast_username=args.vast_username,
        vast_password=args.vast_password,
        vast_cluster_name=args.vast_cluster_name or profile.vast_cluster_name,
        vast_storage_name=args.vast_storage_name or profile.vast_storage_name,
        vast_csi_driver_name=args.vast_csi_driver_name or profile.vast_csi_driver_name,
        vast_vip_pool=args.vast_vip_pool,
        vast_view_policy=args.vast_view_policy,
        driver_type=profile.driver_type,
        provisioner=profile.provisioner,
        vast_subsystem=args.vast_subsystem or profile.vast_subsystem,
        vast_volume_name_format=profile.volume_name_format,
    )


def run_csi_suite(cfg: RunnerConfig) -> int:
    validate_prerequisites(cfg)
    if cfg.ensure_csi_resources:
        ensure_profile_stack(
            cfg.profile,
            kubeconfig=cfg.kubeconfig,
            vast_endpoint=cfg.vast_endpoint,
            csi_namespace=cfg.csi_namespace,
            vast_subsystem=cfg.vast_subsystem,
        )

    print(f"Running CSI certification profile: {cfg.profile}")
    print("Discovering candidate tests...")
    candidates = discover_tests(cfg)
    print(f"Discovered {len(candidates)} tests in suite {cfg.suite!r}.")

    selected = select_tests(candidates, cfg.keywords, cfg.skip_patterns, cfg.max_tests)
    if not selected:
        if candidates:
            selected = candidates[: cfg.max_tests]
            print(
                "No tests matched keyword filters; falling back to first discovered tests: "
                f"{len(selected)} selected."
            )
        else:
            raise RuntimeError(
                "No tests were discovered from openshift-tests dry-run.\n"
                "See discovery logs for details:\n"
                f"  - {cfg.output_dir / 'discovery.with-manifest.log'}\n"
                f"  - {cfg.output_dir / 'discovery.all.log'}\n"
                f"  - {cfg.output_dir / 'discovery.no-manifest.log'}"
            )

    print(f"Selected {len(selected)} tests:")
    for index, test_name in enumerate(selected, start=1):
        print(f"  {index:02d}. {test_name}")

    if cfg.list_only:
        return 0

    results: list[dict[str, object]] = []
    failed = 0
    skipped = 0
    for index, test_name in enumerate(selected, start=1):
        print(f"\n[{index}/{len(selected)}] Running: {test_name}")
        rc, status = run_test_case(cfg, test_name, index)
        if status == "failed":
            failed += 1
        elif status == "skipped":
            skipped += 1
        print(f"Result: {status} (rc={rc})")
        results.append({"name": test_name, "rc": rc, "status": status})

    collect_cluster_metadata(cfg)
    save_summary(cfg, selected, results)
    archive_path = create_archive(cfg)
    print(f"\nSummary written to: {cfg.output_dir / 'summary.json'}")
    print(f"Archive written to: {archive_path}")
    passed = len(selected) - failed - skipped
    print(f"Total: {len(selected)}, Passed: {passed}, Skipped: {skipped}, Failed: {failed}")
    return 1 if failed else 0
