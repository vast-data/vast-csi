"""Shared constants for CSI e2e and certification tests."""
from pathlib import Path
import os

from dotenv import load_dotenv

TESTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
CHARTS_DIR = REPO_ROOT / "charts"

# Existing env vars win; otherwise load IMAGE_TAG / VAST_ENDPOINT from repo .env.
load_dotenv(REPO_ROOT / ".env")

USERNAME = "admin"
PASSWORD = "123456"
CSI_NAMESPACE = "default"
CSI_QUOTA_PREFIX = "csi"
MGMT_SECRET = "vast-mgmt"
VIPPOOL_NAME = "vippool-1"
VIEW_POLICY_NAME = "default"
ROOT_EXPORT = "/k8s"
S3_POLICY_NAME = "s3_default_policy"

NFS_MOUNT_OPTIONS = ["vers=4.1"]

NFS_STORAGE_CLASS = "vastdata-filesystem"
BLOCK_STORAGE_CLASS = "vastdata-block"
BLOCK_SUBSYSTEM = "myblock"
SNAPSHOT_CLASS = "vastdata-snapshot"

# Google's pull-through cache of Docker Hub. Same digests, no unauthenticated
# pull rate limit, so a busy CI run cannot be throttled into failing.
# Keep these tagged: an untagged image means ':latest', which makes Kubernetes
# default to imagePullPolicy 'Always' and re-fetch the manifest for every pod a
# stress wave creates.
BUSYBOX_IMAGE = "mirror.gcr.io/library/busybox:1.37"
AWS_CLI_IMAGE = "mirror.gcr.io/amazon/aws-cli:2.36.48"


# Hard limits every CSI test runs under. CPU is the charts' requests.cpu for
# csiVastPlugin; the charts declare no CPU limit, so that is the only number the
# driver is sized for. Memory is ~1.5x the measured peak under NFSv4 churn
# (49.8MiB controller, 64.8MiB node), deliberately nowhere near the 500Mi chart
# limit, which is the OOM-kill point and far too late to catch anything.
# Block is unmeasured; its node keeps extra CPU for mkfs, fsck, and nvme tools.
CPU_MAX_NFS_CONTROLLER = 100
CPU_MAX_NFS_NODE = 200
CPU_MAX_BLOCK_CONTROLLER = 100
CPU_MAX_BLOCK_NODE = 400
CPU_MAX_COSI_CONTROLLER = 100

MEM_MAX_NFS_CONTROLLER = 80
MEM_MAX_NFS_NODE = 100
MEM_MAX_BLOCK_CONTROLLER = 100
MEM_MAX_BLOCK_NODE = 150
MEM_MAX_COSI_CONTROLLER = 80

# Cadence of the in-run resource table.
RESOURCE_LIVE_REPORT_EVERY = 60


def numbered_name(prefix: str, index: int = 0) -> str:
    """vastdata-filesystem, vastdata-filesystem1, vastdata-filesystem2, ..."""
    return prefix if index == 0 else f"{prefix}{index}"


def nfs_storage_class(index: int = 0) -> str:
    return numbered_name(NFS_STORAGE_CLASS, index)


def block_storage_class(index: int = 0, *, fs_type: str = "ext4") -> str:
    base = numbered_name(BLOCK_STORAGE_CLASS, index)
    return base if fs_type == "ext4" else f"{base}-{fs_type}"


def csi_plugin_image() -> str | None:
    """Full CSI plugin image (``repository:tag``)."""
    return os.environ.get("IMAGE_TAG") or os.environ.get("CSI_IMAGE")
