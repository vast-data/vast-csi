#!/usr/bin/env python3
"""Check that the golden image is ready for kubevirt-storage-checkup discovery."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
_TESTS_DIR = WORK_DIR.parents[1]
_REPO_ROOT = _TESTS_DIR.parent
for _path in (str(_TESTS_DIR), str(_REPO_ROOT), str(WORK_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from csi_runner import _resolve_oc_binary
from kubevirt_checkup import DEFAULT_STORAGE_CLASS, KubeVirtStorageCheckup
from lib.k8s import make_k8s


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify KubeVirt golden image discovery resources.")
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "~/.kube/config"),
        help="Path to kubeconfig used by oc.",
    )
    parser.add_argument("--namespace", default="vast-csi", help="Namespace for the storage checkup job.")
    parser.add_argument(
        "--storage-class",
        default=DEFAULT_STORAGE_CLASS,
        help=f"StorageClass used by the checkup (default: {DEFAULT_STORAGE_CLASS}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    kubeconfig = Path(args.kubeconfig).expanduser().resolve()
    k8s = make_k8s(kubeconfig=kubeconfig, kubectl=_resolve_oc_binary())
    checkup = KubeVirtStorageCheckup(k8s, namespace=args.namespace, storage_class=args.storage_class)
    return 0 if checkup.report_golden_image() else 1


if __name__ == "__main__":
    raise SystemExit(main())
