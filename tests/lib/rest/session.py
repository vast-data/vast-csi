"""Test VmsSession: production session plus test resource analogs.

Used by pytest e2e and by OpenShift certification (same VMS REST client).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from plumbum import local

from vast_csi.session.vms_session import VmsSession

from lib.constants import PASSWORD, USERNAME
from lib.rest.resources import (
    BlockHost,
    BlockHostMapping,
    Cluster,
    Folder,
    GlobalSnapshotStream,
    Plugin,
    ProtectedPath,
    ProtectionPolicy,
    QosPolicy,
    Quota,
    Snapshot,
    Tenant,
    User,
    Version,
    View,
    ViewPolicy,
    VipPool,
    Volume,
)

# Config reads ``version.info`` from CWD at import time.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if "vast_csi.configuration" not in sys.modules:
    with local.cwd(str(_REPO_ROOT)):
        from vast_csi.configuration import Config
else:
    from vast_csi.configuration import Config


class TestVmsSession(VmsSession):
    """``VmsSession`` for tests, with explicit resource analogs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.versions = Version(self)
        self.plugins = Plugin(self)
        self.viewpolicies = ViewPolicy(self)
        self.views = View(self)
        self.quospolicies = QosPolicy(self)
        self.tenants = Tenant(self)
        self.folders = Folder(self)
        self.vippools = VipPool(self)
        self.quotas = Quota(self)
        self.snapshots = Snapshot(self)
        self.globalsnapstreams = GlobalSnapshotStream(self)
        self.users = User(self)
        self.volumes = Volume(self)
        self.blockhosts = BlockHost(self)
        self.blockhostmappings = BlockHostMapping(self)
        self.protectionpolicies = ProtectionPolicy(self)
        self.protectedpaths = ProtectedPath(self)
        self.clusters = Cluster(self)

    @classmethod
    def connect(
        cls,
        *,
        endpoint: str,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        tenant: str | None = None,
    ) -> "TestVmsSession":
        os.environ.setdefault("X_CSI_DISABLE_USAGE_STATS", "true")
        return cls(
            config=Config(),
            username=username or USERNAME,
            password=password or PASSWORD,
            token=token or None,
            tenant=tenant or None,
            endpoint=endpoint,
            ssl_cert=None,
            cluster_name=None,
        )

    @classmethod
    def from_env(cls) -> "TestVmsSession":
        endpoint = os.environ.get("VAST_ENDPOINT")
        if not endpoint:
            raise RuntimeError("VAST_ENDPOINT is required for tests")
        return cls.connect(
            endpoint=endpoint,
            username=os.environ.get("VAST_USERNAME") or USERNAME,
            password=os.environ.get("VAST_PASSWORD") or PASSWORD,
            token=os.environ.get("VAST_TOKEN") or None,
            tenant=os.environ.get("VAST_TENANT") or None,
        )


def session_from_env() -> TestVmsSession:
    return TestVmsSession.from_env()
