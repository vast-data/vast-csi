"""Test VmsSession: production session plus test resource analogs.

Used by pytest e2e and by OpenShift certification (same VMS REST client).
"""
from __future__ import annotations

import io
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
    TlsCertificate,
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


class MultipartVmsSession(VmsSession):
    """``VmsSession`` that can also send ``multipart/form-data`` requests.

    The production session is JSON-only: it json-encodes ``data`` and pins
    ``Content-Type: application/json``. VMS endpoints that accept file uploads
    (``/tlscertificates/``) need real multipart parts plus the boundary that
    only ``requests`` can generate, so multipart shaping lives here instead of
    in ``vast_csi``.
    """

    def request_multipart(
        self,
        verb: str,
        api_method: str,
        *args,
        fields: dict | None = None,
        files: dict | None = None,
        **kwargs,
    ):
        """Send *fields* and *files* as ``multipart/form-data``.

        *fields* are plain form values, *files* map a part name to a
        ``(filename, content, content_type)`` tuple.
        """
        # Every part goes through ``files``: production json-encodes ``data``,
        # which would turn form fields into a JSON blob.
        parts: dict = {name: (None, str(value)) for name, value in (fields or {}).items()}
        for name, spec in (files or {}).items():
            filename, content, *rest = spec
            if isinstance(content, (bytes, str)):
                # File-like keeps request logging readable (no PEM dump in logs).
                content = io.BytesIO(content.encode() if isinstance(content, str) else content)
            parts[name] = (filename, content, *rest)

        # requests drops headers merged as None, so the session's
        # application/json gives way to multipart/form-data + boundary.
        headers = dict(kwargs.pop("headers", None) or {})
        headers["Content-Type"] = None

        # Call request() directly: requests.Session.post() would inject data=None.
        return self.request(verb.upper(), api_method, *args, files=parts, headers=headers, **kwargs)

    def post_multipart(self, api_method: str, *args, **kwargs):
        return self.request_multipart("POST", api_method, *args, **kwargs)


class TestVmsSession(MultipartVmsSession):
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
        self.tlscertificates = TlsCertificate(self)

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
