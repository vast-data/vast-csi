#!/usr/bin/env python3
"""Run KubeVirt storage checkup certification for VAST CSI."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(WORK_DIR))
from csi_runner import ensure_profile_stack


def _resolve_oc_binary() -> str | None:
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


def prepare_output_dir(work_dir: Path, explicit_output: str | None) -> Path:
    output_root = work_dir / "output" / "kubevirt"
    output_root.mkdir(parents=True, exist_ok=True)
    for item in output_root.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)
    output_dir = Path(explicit_output) if explicit_output else output_root / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir.resolve()


def collect_metadata(oc_bin: str, kubeconfig: Path, output_dir: Path, namespace: str) -> None:
    meta_dir = output_dir / "cluster-metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    commands = {
        "clusterversion.yaml": [oc_bin, "--kubeconfig", str(kubeconfig), "get", "clusterversion", "-o", "yaml"],
        "storageclasses.yaml": [oc_bin, "--kubeconfig", str(kubeconfig), "get", "sc", "-o", "yaml"],
        "storage-checkup-config.yaml": [
            oc_bin,
            "--kubeconfig",
            str(kubeconfig),
            "-n",
            namespace,
            "get",
            "configmap",
            "storage-checkup-config",
            "-o",
            "yaml",
        ],
    }
    for filename, cmd in commands.items():
        result = subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (meta_dir / filename).write_text(result.stdout or "", encoding="utf-8")


def create_archive(output_dir: Path) -> Path:
    archive = output_dir.parent / f"{output_dir.name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(output_dir, arcname=f"kubevirt/{output_dir.name}")
    return archive


def run_script_live(cmd: list[str], env: dict[str, str], log_path: Path) -> int:
    """Run a shell script with stdout/stderr streamed to the terminal and log file."""
    if shutil.which("stdbuf"):
        cmd = ["stdbuf", "-oL", "-eL", *cmd]

    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
            log_file.flush()
        return proc.wait()


def read_checkup_succeeded(oc_bin: str, kubeconfig: Path, namespace: str) -> tuple[bool, str]:
    result = subprocess.run(
        [
            oc_bin,
            "--kubeconfig",
            str(kubeconfig),
            "-n",
            namespace,
            "get",
            "configmap",
            "storage-checkup-config",
            "-o",
            "jsonpath={.data.status\\.succeeded}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    value = (result.stdout or "").strip()
    if result.returncode != 0:
        return False, value or "configmap storage-checkup-config not found"
    return value == "true", value or "missing status.succeeded"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run KubeVirt storage checkup certification.")
    parser.add_argument(
        "--profile",
        choices=("nfs", "block"),
        default="nfs",
        help="Storage profile for the checkup (default: nfs).",
    )
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "~/.kube/config"),
        help="Path to kubeconfig used by oc.",
    )
    parser.add_argument("--namespace", default="vast-csi", help="Namespace for the storage checkup job.")
    parser.add_argument(
        "--storage-class",
        default=None,
        help="StorageClass to test. Default: vastdata-filesystem (nfs) or vastdata-block (block).",
    )
    parser.add_argument("--output-dir", default=None, help="Where to write results. Default: output/kubevirt/<timestamp>.")
    parser.add_argument("--cleanup-first", action="store_true", help="Run cleanup-kubevirt.sh before the checkup.")
    parser.add_argument("--vast-endpoint", default=os.environ.get("VAST_ENDPOINT"), help="VAST management endpoint.")
    parser.add_argument("--vast-subsystem", default="redhat-e2e-block", help="Block subsystem name (block profile only).")
    parser.add_argument(
        "--skip-ensure-csi-resources",
        action="store_true",
        help="Skip automatic VastCluster/VastStorage/VastCSIDriver apply.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kubeconfig = Path(args.kubeconfig).expanduser().resolve()
    output_dir = prepare_output_dir(WORK_DIR, args.output_dir)
    oc_bin = _resolve_oc_binary()
    if not oc_bin:
        raise RuntimeError("Cannot find executable 'oc' binary.")

    storage_class = args.storage_class or ("vastdata-filesystem" if args.profile == "nfs" else "vastdata-block")
    script_name = "run-kubevirt.sh" if args.profile == "nfs" else "run-kubevirt-block.sh"
    script_path = WORK_DIR / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Missing KubeVirt script: {script_path}")

    env = os.environ.copy()
    env["KUBECONFIG"] = str(kubeconfig)

    if args.cleanup_first:
        cleanup = WORK_DIR / "scripts" / "cleanup-kubevirt.sh"
        run_script_live([str(cleanup)], env, output_dir / "kubevirt-cleanup.log")

    # vastdata-filesystem is required for NFS golden images and CDI scratch space.
    ensure_profile_stack(
        "nfs",
        kubeconfig=kubeconfig,
        vast_endpoint=args.vast_endpoint,
        csi_namespace=args.namespace,
        skip=args.skip_ensure_csi_resources,
    )
    if args.profile == "block":
        ensure_profile_stack(
            "block",
            kubeconfig=kubeconfig,
            vast_endpoint=args.vast_endpoint,
            csi_namespace=args.namespace,
            vast_subsystem=args.vast_subsystem,
            skip=args.skip_ensure_csi_resources,
        )

    log_path = output_dir / "kubevirt-checkup.log"
    print(f"Running KubeVirt storage checkup profile={args.profile} storageClass={storage_class}")
    script_rc = run_script_live([str(script_path), args.namespace, storage_class], env, log_path)

    collect_metadata(oc_bin, kubeconfig, output_dir, args.namespace)
    checkup_ok, checkup_detail = read_checkup_succeeded(oc_bin, kubeconfig, args.namespace)

    if script_rc != 0:
        status = "failed"
        failure_reason = f"checkup script exited with code {script_rc}"
    elif not checkup_ok:
        status = "failed"
        failure_reason = f"storage-checkup-config status.succeeded is not true ({checkup_detail!r})"
    else:
        status = "passed"
        failure_reason = ""

    summary = {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "profile": "kubevirt",
        "storage_profile": args.profile,
        "storage_class": storage_class,
        "namespace": args.namespace,
        "status": status,
        "succeeded": status == "passed",
        "script_exit_code": script_rc,
        "checkup_succeeded": checkup_detail,
        "failure_reason": failure_reason,
        "log": str(log_path),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    archive_path = create_archive(output_dir)
    print(f"\nSummary written to: {output_dir / 'summary.json'}")
    print(f"Archive written to: {archive_path}")
    print(f"Result: {status}")
    if failure_reason:
        print(f"Reason: {failure_reason}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
