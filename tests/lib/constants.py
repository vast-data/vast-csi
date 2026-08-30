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

BUSYBOX_IMAGE = "docker.io/library/busybox"
AWS_CLI_IMAGE = "docker.io/amazon/aws-cli"


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
