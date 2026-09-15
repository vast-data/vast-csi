#!/usr/bin/env python3
"""Single entry point for Red Hat/OpenShift certification: nfs, block, or kubevirt."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
_TESTS_DIR = WORK_DIR.parents[1]
_REPO_ROOT = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(_REPO_ROOT), str(WORK_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from csi_runner import (
    DEFAULT_VAST_PASSWORD,
    DEFAULT_VAST_USERNAME,
    PROFILES,
    _resolve_oc_binary,
    build_config,
    ensure_profile_stack,
    run_csi_suite,
)
from kubevirt_checkup import (
    CHECKUP_CONFIG,
    DEFAULT_STORAGE_CLASS,
    KubeVirtStorageCheckup,
    format_redhat_checkup_log,
)
from lib.constants import VIEW_POLICY_NAME, VIPPOOL_NAME
from lib.k8s import make_k8s


# ---------------------------------------------------------------------------
# KubeVirt helpers
# ---------------------------------------------------------------------------

def _prepare_kubevirt_output_dir(explicit_output: str | None) -> Path:
    output_root = WORK_DIR / "output" / "kubevirt"
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(explicit_output) if explicit_output else output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def _prune_old_kubevirt_output(output_root: Path, keep: Path) -> None:
    keep = keep.resolve()
    keep_archive = output_root / f"{keep.name}.tar.gz"
    for item in output_root.iterdir():
        resolved = item.resolve()
        if resolved == keep or resolved == keep_archive.resolve():
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def _archive_kubevirt_log(log_path: Path) -> Path:
    archive = log_path.parent.parent / f"{log_path.parent.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(log_path, arcname="kubevirt-checkup.log")
    return archive


def _kubevirt_evidence_from_cluster(k8s, namespace: str) -> dict:
    pods = k8s.pods.get(namespace=namespace, labels={"job-name": "storage-checkup"}) or []
    pod_name = pods[0].metadata.name if pods else "storage-checkup"
    job_logs = ""
    cm_yaml = ""
    phase = "Unknown"
    succeeded = "false"
    try:
        job_logs = k8s.kubectl("logs", f"pod/{pod_name}", "-n", namespace) or ""
    except Exception:
        pass
    try:
        cm_yaml = k8s.kubectl("get", "configmap", CHECKUP_CONFIG, "-n", namespace, "-o", "yaml") or ""
    except Exception:
        pass
    if pods:
        phase = str((pods[0].get("status") or {}).get("phase") or "Unknown")
    if 'status.succeeded: "true"' in cm_yaml or "status.succeeded: 'true'" in cm_yaml:
        succeeded = "true"
    return {
        "pod_name": pod_name,
        "job_logs": job_logs,
        "configmap_yaml": cm_yaml,
        "final_phase": phase,
        "succeeded": succeeded,
    }


def run_kubevirt_suite(args: argparse.Namespace) -> int:
    kubeconfig = Path(args.kubeconfig).expanduser().resolve()
    output_dir = _prepare_kubevirt_output_dir(args.output_dir)
    oc_bin = _resolve_oc_binary()
    k8s = make_k8s(kubeconfig=kubeconfig, kubectl=oc_bin)
    checkup = KubeVirtStorageCheckup(k8s, namespace=args.namespace, storage_class=args.storage_class)
    log_path = output_dir / "kubevirt-checkup.log"

    print(f"Running KubeVirt storage checkup storageClass={args.storage_class}")
    failure_reason = ""
    status = "passed"
    evidence: dict = {}
    try:
        ensure_profile_stack(
            "nfs",
            kubeconfig=kubeconfig,
            vast_endpoint=args.vast_endpoint,
            csi_namespace=args.namespace,
        )
        if args.cleanup_first or args.reimport_golden_image:
            checkup.cleanup_previous(reimport_golden_image=args.reimport_golden_image)
        evidence = checkup.run()
        checkup.assert_succeeded()
    except Exception as exc:
        status = "failed"
        failure_reason = str(exc)
        print(f"[ERROR] {failure_reason}")
        if not evidence:
            try:
                evidence = _kubevirt_evidence_from_cluster(k8s, args.namespace)
            except Exception:
                evidence = {}

    log_path.write_text(
        format_redhat_checkup_log(
            namespace=args.namespace,
            pod_name=str(evidence.get("pod_name") or "storage-checkup"),
            job_logs=str(evidence.get("job_logs") or ""),
            configmap_yaml=str(evidence.get("configmap_yaml") or ""),
            final_phase=str(evidence.get("final_phase") or "Unknown"),
            succeeded=str(evidence.get("succeeded") or "false"),
        ),
        encoding="utf-8",
    )

    checkup_ok, checkup_detail = checkup.checkup_status()
    if status == "passed" and not checkup_ok:
        status = "failed"
        failure_reason = f"storage-checkup-config status.succeeded is not true ({checkup_detail!r})"

    archive_path = _archive_kubevirt_log(log_path)
    _prune_old_kubevirt_output(output_dir.parent, output_dir)
    print(f"\nJob log written to: {log_path}")
    print(f"Archive written to: {archive_path}")
    print(f"Result: {status}")
    if failure_reason:
        print(f"Reason: {failure_reason}")
    return 0 if status == "passed" else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run VAST OpenShift certification (one suite at a time).",
    )
    parser.add_argument(
        "suite",
        choices=("nfs", "block", "kubevirt"),
        help="Certification suite to run.",
    )

    # Shared
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "~/.kube/config"),
        help="Path to kubeconfig.",
    )
    parser.add_argument(
        "--vast-endpoint",
        default=os.environ.get("VAST_ENDPOINT"),
        help="VAST management endpoint (ip/fqdn).",
    )
    parser.add_argument("--output-dir", default=None, help="Where to write results.")

    # CSI (nfs / block)
    parser.add_argument("--list-only", action="store_true", help="CSI only: discover and print selected tests.")
    parser.add_argument("--manifest", default=None, help="CSI only: path to external test manifest.")
    parser.add_argument("--image", default="registry.redhat.io/openshift4/ose-tests", help="CSI only: ose-tests image.")
    parser.add_argument("--suite-name", default="openshift/csi", dest="suite_name", help="CSI only: openshift-tests suite.")
    parser.add_argument("--keyword", action="append", default=None, help="CSI only: include tests matching keyword.")
    parser.add_argument("--skip-pattern", action="append", default=None, help="CSI only: exclude tests matching keyword.")
    parser.add_argument("--max-tests", type=int, default=24, help="CSI only: max selected tests.")
    parser.add_argument("--csi-namespace", default="vast-csi", help="Namespace for CSI custom resources.")
    parser.add_argument("--vast-username", default=DEFAULT_VAST_USERNAME, help="VAST username.")
    parser.add_argument("--vast-password", default=DEFAULT_VAST_PASSWORD, help="VAST password.")
    parser.add_argument("--vast-cluster-name", default=None, help="VastCluster metadata.name.")
    parser.add_argument("--vast-storage-name", default=None, help="VastStorage metadata.name.")
    parser.add_argument("--vast-csi-driver-name", default=None, help="VastCSIDriver metadata.name.")
    parser.add_argument("--vast-vip-pool", default=VIPPOOL_NAME, help="VastStorage spec.vipPool.")
    parser.add_argument("--vast-view-policy", default=VIEW_POLICY_NAME, help="VastStorage spec.viewPolicy (NFS).")

    # KubeVirt
    parser.add_argument("--namespace", default="vast-csi", help="KubeVirt only: checkup namespace.")
    parser.add_argument(
        "--storage-class",
        default=DEFAULT_STORAGE_CLASS,
        help=f"KubeVirt only: StorageClass (default: {DEFAULT_STORAGE_CLASS}).",
    )
    parser.add_argument(
        "--cleanup-first",
        action="store_true",
        help="KubeVirt only: delete previous checkup job/VMs first (keeps golden image).",
    )
    parser.add_argument(
        "--reimport-golden-image",
        action="store_true",
        help="KubeVirt only: delete and re-download/convert the golden image.",
    )

    args = parser.parse_args()
    if args.suite in PROFILES and args.manifest is None:
        args.manifest = str(WORK_DIR / PROFILES[args.suite].manifest)
    return args


def _csi_args(args: argparse.Namespace) -> argparse.Namespace:
    """Adapt CLI args to the shape expected by csi_runner.build_config()."""
    return argparse.Namespace(
        profile=args.suite,
        kubeconfig=args.kubeconfig,
        manifest=args.manifest,
        output_dir=args.output_dir,
        image=args.image,
        suite=args.suite_name,
        keyword=args.keyword,
        skip_pattern=args.skip_pattern,
        max_tests=args.max_tests,
        list_only=args.list_only,
        csi_namespace=args.csi_namespace,
        vast_endpoint=args.vast_endpoint,
        vast_username=args.vast_username,
        vast_password=args.vast_password,
        vast_cluster_name=args.vast_cluster_name,
        vast_storage_name=args.vast_storage_name,
        vast_csi_driver_name=args.vast_csi_driver_name,
        vast_vip_pool=args.vast_vip_pool,
        vast_view_policy=args.vast_view_policy,
    )


def main() -> int:
    args = parse_args()
    if args.suite in ("nfs", "block"):
        return run_csi_suite(build_config(_csi_args(args)))
    return run_kubevirt_suite(args)


if __name__ == "__main__":
    raise SystemExit(main())
