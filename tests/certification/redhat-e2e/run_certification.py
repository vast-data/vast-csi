#!/usr/bin/env python3
"""Orchestrate Red Hat/OpenShift certification suites for NFS, block, and KubeVirt."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _run_script(script: Path, extra_args: list[str]) -> int:
    cmd = [sys.executable, str(script), *extra_args]
    print(f"\n=== Running: {' '.join(cmd)} ===\n")
    return subprocess.run(cmd, check=False).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VAST OpenShift certification suites.")
    parser.add_argument(
        "suite",
        choices=("nfs", "block", "kubevirt", "all"),
        help="Which certification suite to run.",
    )
    parser.add_argument("--kubeconfig", default=None, help="Path to kubeconfig.")
    parser.add_argument("--vast-endpoint", default=None, help="VAST management endpoint.")
    parser.add_argument("--list-only", action="store_true", help="For CSI suites, only list selected tests.")
    parser.add_argument("--skip-ensure-csi-resources", action="store_true", help="Skip automatic CR setup for CSI suites.")
    parser.add_argument(
        "--kubevirt-profile",
        choices=("nfs", "block"),
        default="nfs",
        help="Storage profile for KubeVirt checkup when suite is kubevirt or all.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    work_dir = Path(__file__).resolve().parent
    shared_args: list[str] = []
    if args.kubeconfig:
        shared_args.extend(["--kubeconfig", args.kubeconfig])
    if args.vast_endpoint:
        shared_args.extend(["--vast-endpoint", args.vast_endpoint])
    if args.list_only:
        shared_args.append("--list-only")
    if args.skip_ensure_csi_resources:
        shared_args.append("--skip-ensure-csi-resources")

    exit_codes: dict[str, int] = {}

    if args.suite in ("nfs", "all"):
        exit_codes["nfs"] = _run_script(
            work_dir / "run_csi.py",
            ["--profile", "nfs", *shared_args],
        )

    if args.suite in ("block", "all"):
        exit_codes["block"] = _run_script(
            work_dir / "run_csi.py",
            ["--profile", "block", *shared_args],
        )

    if args.suite in ("kubevirt", "all"):
        kubevirt_args = ["--profile", args.kubevirt_profile, *shared_args]
        if args.vast_endpoint:
            kubevirt_args.extend(["--vast-endpoint", args.vast_endpoint])
        if args.skip_ensure_csi_resources:
            kubevirt_args.append("--skip-ensure-csi-resources")
        exit_codes["kubevirt"] = _run_script(work_dir / "run_kubevirt.py", kubevirt_args)

    print("\n=== Certification summary ===")
    for name, code in exit_codes.items():
        print(f"  {name}: {'passed' if code == 0 else 'failed'} (rc={code})")

    return 1 if any(code != 0 for code in exit_codes.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
