#!/usr/bin/env python3
"""Run KubeVirt storage checkup certification for VAST CSI (NFS)."""

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

from csi_runner import _resolve_oc_binary, ensure_profile_stack
from kubevirt_checkup import (
    CHECKUP_CONFIG,
    DEFAULT_STORAGE_CLASS,
    KubeVirtStorageCheckup,
    format_redhat_checkup_log,
)
from lib.k8s import make_k8s


def prepare_output_dir(work_dir: Path, explicit_output: str | None) -> Path:
    output_root = work_dir / "output" / "kubevirt"
    output_root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(explicit_output) if explicit_output else output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def prune_old_kubevirt_output(output_root: Path, keep: Path) -> None:
    """Keep only the current run directory and its archive."""
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


def create_archive(log_path: Path) -> Path:
    archive = log_path.parent.parent / f"{log_path.parent.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(log_path, arcname="kubevirt-checkup.log")
    return archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run KubeVirt storage checkup certification on NFS.")
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "~/.kube/config"),
        help="Path to kubeconfig used by oc.",
    )
    parser.add_argument("--namespace", default="vast-csi", help="Namespace for the storage checkup job.")
    parser.add_argument(
        "--storage-class",
        default=DEFAULT_STORAGE_CLASS,
        help=f"StorageClass to test (default: {DEFAULT_STORAGE_CLASS}).",
    )
    parser.add_argument("--output-dir", default=None, help="Where to write results. Default: output/kubevirt/<timestamp>.")
    parser.add_argument(
        "--cleanup-first",
        action="store_true",
        help="Delete previous checkup job/VMs first. Does not delete a downloaded/converted golden image.",
    )
    parser.add_argument(
        "--reimport-golden-image",
        action="store_true",
        help="Delete golden-image DataVolumes/PVCs and download/convert again.",
    )
    parser.add_argument("--vast-endpoint", default=os.environ.get("VAST_ENDPOINT"), help="VAST management endpoint.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kubeconfig = Path(args.kubeconfig).expanduser().resolve()
    output_dir = prepare_output_dir(WORK_DIR, args.output_dir)
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
                evidence = _evidence_from_cluster(k8s, args.namespace)
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

    archive_path = create_archive(log_path)
    prune_old_kubevirt_output(output_dir.parent, output_dir)
    print(f"\nJob log written to: {log_path}")
    print(f"Archive written to: {archive_path}")
    print(f"Result: {status}")
    if failure_reason:
        print(f"Reason: {failure_reason}")
    return 0 if status == "passed" else 1


def _evidence_from_cluster(k8s, namespace: str) -> dict:
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
    if "status.succeeded: \"true\"" in cm_yaml or "status.succeeded: 'true'" in cm_yaml:
        succeeded = "true"
    return {
        "pod_name": pod_name,
        "job_logs": job_logs,
        "configmap_yaml": cm_yaml,
        "final_phase": phase,
        "succeeded": succeeded,
    }


if __name__ == "__main__":
    raise SystemExit(main())
