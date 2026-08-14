"""E2E VmsSession: production session plus test-only helpers on each resource."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from easypy.bunch import Bunch
from plumbum import local

from vast_csi.session.resources import VastResource
from vast_csi.session.vms_session import VmsSession

from e2e.constants import VIPPOOL_NAME
from e2e.logging import logger
from e2e.rest.resources import TestResourceMixin, extend_resource

# Config reads ``version.info`` from CWD at import time.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if "vast_csi.configuration" not in sys.modules:
    with local.cwd(str(_REPO_ROOT)):
        from vast_csi.configuration import Config
else:
    from vast_csi.configuration import Config


class E2EVmsSession(VmsSession):
    """``VmsSession`` for real-cluster tests.

    After init each resource instance is rebound to a class that also includes
    ``TestResourceMixin`` (``single`` / iteration).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._extend_resources()

    def _extend_resources(self) -> None:
        for name, value in list(vars(self).items()):
            if isinstance(value, VastResource) and not isinstance(value, TestResourceMixin):
                setattr(self, name, extend_resource(value))

    @classmethod
    def from_env(cls) -> "E2EVmsSession":
        def _get(suffix: str, default: str | None = None) -> str | None:
            return os.environ.get(f"VAST_{suffix}", default)

        endpoint = _get("ENDPOINT")
        if not endpoint:
            raise RuntimeError("VAST_ENDPOINT is required for e2e tests")

        os.environ.setdefault("X_CSI_DISABLE_USAGE_STATS", "true")
        session = cls(
            config=Config(),
            username=_get("USERNAME", "admin") or "admin",
            password=_get("PASSWORD", "123456") or "123456",
            token=_get("TOKEN") or None,
            tenant=_get("TENANT") or None,
            endpoint=endpoint,
            ssl_cert=None,
            cluster_name=None,
        )
        session.vippool_name = VIPPOOL_NAME
        session.view_policy_name = _get("VIEW_POLICY", "default") or "default"
        session.root_export = _get("ROOT_EXPORT", "/k8s") or "/k8s"
        session.s3_policy_name = _get("S3_POLICY", "s3_default_policy") or "s3_default_policy"
        return session

    def ensure_export(
        self,
        path: str,
        *,
        protocols: list[str] | None = None,
        policy: str | None = None,
    ) -> Bunch:
        """Ensure a view at *path* exposes NFS and NFS4.

        ``View.ensure`` returns an existing view unchanged, so an NFS-only root
        export would stay NFS-only. Patch protocols when NFS4 is missing.
        """
        protocols = list(protocols or ["NFS", "NFS4"])
        policy_name = policy or self.view_policy_name
        path = path if path == "/" else (path.rstrip("/") or "/")

        view = self.views.one(path=path, policy__name=policy_name)
        if not view:
            logger.info(f"Creating export {path} protocols={protocols} policy={policy_name}")
            return self.views.ensure(
                path=path,
                protocols=protocols,
                view_policy=policy_name,
                qos_policy=None,
                create_dir=(path != "/"),
            )

        current = [str(p).upper() for p in (view.protocols or [])]
        missing = [p for p in protocols if p.upper() not in current]
        if missing:
            updated = current + missing
            logger.info(f"Updating export {path} protocols {current} -> {updated}")
            self.views.update(view.id, protocols=updated)
            view.protocols = updated
        else:
            logger.info(f"Export {path} already has protocols {current}")
        return view

    def verify_vip_connectivity(self, pings: int = 2) -> str:
        """Pick a VIP from vippool-1 and ping it before the suite runs."""
        vip = self.vippools.get_vip(self.vippool_name)
        logger.info(f"Probing datapath: ping {vip} ({pings} times, pool {self.vippool_name!r})")
        try:
            local.cmd.ping("-c", str(pings), "-W", "2", vip)
        except Exception as exc:
            raise RuntimeError(
                f"No connectivity from this machine to VAST VIP {vip} "
                f"(pool {self.vippool_name!r}): {exc}"
            ) from exc
        logger.info(f"VIP {vip} is reachable")
        return vip


def session_from_env() -> E2EVmsSession:
    return E2EVmsSession.from_env()
