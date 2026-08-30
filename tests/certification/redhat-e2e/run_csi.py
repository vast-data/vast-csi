#!/usr/bin/env python3
"""Run Red Hat/OpenShift CSI certification for NFS or block profiles."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WORK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(WORK_DIR))
from csi_runner import (
    DEFAULT_VAST_PASSWORD,
    DEFAULT_VAST_USERNAME,
    PROFILES,
    build_config,
    run_csi_suite,
)
from lib.constants import VIEW_POLICY_NAME, VIPPOOL_NAME


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OpenShift CSI certification for NFS or block.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="nfs",
        help="Certification profile to run (default: nfs).",
    )
    parser.add_argument(
        "--kubeconfig",
        default=os.environ.get("KUBECONFIG", "~/.kube/config"),
        help="Path to kubeconfig used by openshift-tests.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to CSI external test manifest. Default depends on profile.",
    )
    parser.add_argument("--output-dir", default=None, help="Where to write results. Default: output/<profile>/<timestamp>.")
    parser.add_argument("--image", default="registry.redhat.io/openshift4/ose-tests", help="Container image that provides openshift-tests.")
    parser.add_argument("--suite", default="openshift/csi", help="openshift-tests suite to discover tests from.")
    parser.add_argument("--keyword", action="append", default=None, help="Include tests matching this keyword.")
    parser.add_argument("--skip-pattern", action="append", default=None, help="Exclude tests matching this keyword.")
    parser.add_argument("--max-tests", type=int, default=12, help="Maximum number of selected tests.")
    parser.add_argument("--list-only", action="store_true", help="Discover + print selected tests without running them.")
    parser.add_argument("--csi-namespace", default="vast-csi", help="Namespace for CSI custom resources.")
    parser.add_argument("--vast-endpoint", default=os.environ.get("VAST_ENDPOINT"), help="VAST management endpoint (ip/fqdn) for VastCluster.")
    parser.add_argument("--vast-username", default=DEFAULT_VAST_USERNAME, help="VAST username for VastCluster.")
    parser.add_argument("--vast-password", default=DEFAULT_VAST_PASSWORD, help="VAST password for VastCluster.")
    parser.add_argument("--vast-cluster-name", default=None, help="VastCluster metadata.name.")
    parser.add_argument("--vast-storage-name", default=None, help="VastStorage metadata.name.")
    parser.add_argument("--vast-csi-driver-name", default=None, help="VastCSIDriver metadata.name.")
    parser.add_argument("--vast-vip-pool", default=VIPPOOL_NAME, help="VastStorage spec.vipPool.")
    parser.add_argument("--vast-view-policy", default=VIEW_POLICY_NAME, help="VastStorage spec.viewPolicy for NFS profile.")
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    if args.manifest is None:
        args.manifest = str(WORK_DIR / profile.manifest)
    return args


def main() -> int:
    cfg = build_config(parse_args())
    return run_csi_suite(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
