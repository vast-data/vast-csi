"""E2E VMS resource classes: production resources plus test helpers.

Each analog inherits the production class so the VMS API stays unchanged
(``session.views.ensure``, ``session.quotas.one``, …) and adds
``single`` / iteration used by e2e assertions.
"""
from __future__ import annotations

from typing import Any, Callable

from easypy.bunch import Bunch
from easypy.timing import wait
from plumbum import local

from vast_csi.exceptions import ApiError
from vast_csi.session import resources as vms
from vast_csi.session.resources import VastResource

from lib.constants import VIEW_POLICY_NAME, VIPPOOL_NAME
from lib.logging import logger


class TestRecord:
    """One VMS object (quota, view, …) with live lookups for test assertions."""

    def __init__(self, data: Any, resource: VastResource):
        self._data = data if isinstance(data, Bunch) else Bunch.from_dict(data)
        self._resource = resource

    def __getattr__(self, name: str):
        return getattr(self._data, name)

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, *args, **kwargs):
        return self._data.get(*args, **kwargs)

    def __repr__(self):
        name = self._data.get("name") or self._data.get("id")
        return f"<{type(self._resource).__name__} {name}>"

    def _refresh(self):
        rid = self._data.get("id")
        if rid is None:
            return None
        return self._resource.get(rid, fail_if_missing=False)

    @property
    def hard_limit(self):
        return self._data.get("hard_limit") or self._data.get("hard_limit_bytes") or 0

    @property
    def used_capacity(self):
        fresh = self._refresh()
        if fresh is None:
            return 0
        data = fresh._data if isinstance(fresh, TestRecord) else fresh
        return data.get("used_effective_capacity") or data.get("used_capacity") or 0

    @property
    def was_removed(self) -> bool:
        return self._refresh() is None

    @property
    def path(self):
        return self._data.get("path")


class TestResourceMixin:
    """Predicate helpers and iteration over ``list()`` for e2e tests."""

    def _wrap(self, item: Any):
        if item is None or isinstance(item, TestRecord):
            return item
        return TestRecord(item, self)

    def __iter__(self):
        return (self._wrap(item) for item in self.list())

    def __len__(self):
        return len(self.list())

    def single(self, pred: Callable[[Any], bool]):
        found = [item for item in self if pred(item)]
        return found[0] if found else None

    def choose(self, pred: Callable[[Any], bool]):
        found = self.single(pred)
        if found is None:
            raise LookupError(f"no matching {type(self).__name__} record")
        return found


class Version(TestResourceMixin, vms.Version):
    pass


class Plugin(TestResourceMixin, vms.Plugin):
    pass


class ViewPolicy(TestResourceMixin, vms.ViewPolicy):
    def ensure_no_root_squash(self, name: str | None = None) -> Bunch:
        """Clear nfs_root_squash and allow nfs_no_squash=* (KubeVirt/CSI chown on NFS)."""
        policy_name = name or VIEW_POLICY_NAME
        policy = self.one(name=policy_name, fail_if_missing=True)
        desired_root: list[str] = []
        desired_no = ["*"]
        desired_auth = False
        current_root = [str(item) for item in (policy.get("nfs_root_squash") or [])]
        current_no = [str(item) for item in (policy.get("nfs_no_squash") or [])]
        current_auth = policy.get("use_auth_provider")
        if current_root == desired_root and current_no == desired_no and current_auth is desired_auth:
            logger.info(f"View policy {policy_name!r} already has no root squash")
            return policy

        logger.info(
            f"Updating view policy {policy_name!r}: "
            f"nfs_root_squash {current_root} -> {desired_root}, "
            f"nfs_no_squash {current_no} -> {desired_no}"
        )
        self.update(
            policy.id,
            nfs_root_squash=desired_root,
            nfs_no_squash=desired_no,
            use_auth_provider=desired_auth,
        )
        policy.nfs_root_squash = desired_root
        policy.nfs_no_squash = desired_no
        policy.use_auth_provider = desired_auth
        return policy

    def ensure_plain_nfs(self, name: str | None = None) -> Bunch:
        """Allow plain NFSv4 (no xprtsec) for CRC/KubeVirt StorageClass mountOptions.

        Lab clusters may ship ``nfs_enforce_tls=True`` on ``default``. CSI then
        rejects CreateVolume unless the StorageClass sets ``xprtsec=tls|mtls``.
        """
        policy_name = name or VIEW_POLICY_NAME
        policy = self.one(name=policy_name, fail_if_missing=True)
        if not policy.get("nfs_enforce_tls") and not policy.get("nfs_enforce_mtls"):
            logger.info(f"View policy {policy_name!r} already allows plain NFS")
            return policy

        logger.info(
            f"Updating view policy {policy_name!r}: "
            f"nfs_enforce_tls {policy.get('nfs_enforce_tls')} -> False, "
            f"nfs_enforce_mtls {policy.get('nfs_enforce_mtls')} -> False"
        )
        self.update(
            policy.id,
            nfs_enforce_tls=False,
            nfs_enforce_mtls=False,
        )
        policy.nfs_enforce_tls = False
        policy.nfs_enforce_mtls = False
        return policy


class View(TestResourceMixin, vms.View):
    def ensure_export(
        self,
        path: str,
        *,
        protocols: list[str] | None = None,
        policy: str | None = None,
    ) -> Bunch:
        """Ensure a view at *path* exposes NFS and NFS4.

        Production ``ensure`` returns an existing view unchanged, so an NFS-only
        root export would stay NFS-only. Patch protocols when NFS4 is missing.
        """
        protocols = list(protocols or ["NFS", "NFS4"])
        policy_name = policy or VIEW_POLICY_NAME
        path = path if path == "/" else (path.rstrip("/") or "/")

        view = self.one(path=path, policy__name=policy_name)
        if not view:
            logger.info(f"Creating export {path} protocols={protocols} policy={policy_name}")
            return self.ensure(
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
            self.update(view.id, protocols=updated)
            view.protocols = updated
        else:
            logger.info(f"Export {path} already has protocols {current}")
        return view

    def ensure_subsystem(
        self,
        path: str,
        subsystem: str,
        policy: str | None = None,
    ) -> Bunch:
        """Ensure a BLOCK view (NVMe-oF subsystem) exists. Required before block CSI tests."""
        policy_name = policy or VIEW_POLICY_NAME
        view = self.one(name=subsystem)
        if view:
            protocols = [str(p).upper() for p in (view.protocols or [])]
            if "BLOCK" not in protocols:
                raise RuntimeError(
                    f"View {subsystem!r} exists but is not a BLOCK subsystem (protocols={view.protocols})"
                )
            logger.info(f"BLOCK subsystem {subsystem!r} already exists at {view.path}")
            return view

        view_policy = self.session.viewpolicies.one(name=policy_name, fail_if_missing=True)
        logger.info(f"Creating BLOCK subsystem {subsystem!r} at {path} policy={policy_name}")
        return self.create(
            path=path,
            name=subsystem,
            protocols=["BLOCK"],
            policy_id=view_policy.id,
            tenant_id=view_policy.tenant_id,
            create_dir=True,
        )


class QosPolicy(TestResourceMixin, vms.QosPolicy):
    pass


class Tenant(TestResourceMixin, vms.Tenant):
    pass


class Folder(TestResourceMixin, vms.Folder):
    pass


class VipPool(TestResourceMixin, vms.VipPool):
    def verify_vip_connectivity(self, pings: int = 2) -> str:
        """Pick a VIP from the e2e pool and ping it before the suite runs."""
        vip = self.get_vip(VIPPOOL_NAME)
        logger.info(f"Probing datapath: ping {vip} ({pings} times, pool {VIPPOOL_NAME!r})")
        try:
            local.cmd.ping("-c", str(pings), "-W", "2", vip)
        except Exception as exc:
            raise RuntimeError(
                f"No connectivity from this machine to VAST VIP {vip} "
                f"(pool {VIPPOOL_NAME!r}): {exc}"
            ) from exc
        logger.info(f"VIP {vip} is reachable")
        return vip


class Quota(TestResourceMixin, vms.Quota):
    pass


class Snapshot(TestResourceMixin, vms.Snapshot):
    pass


class GlobalSnapshotStream(TestResourceMixin, vms.GlobalSnapshotStream):
    pass


class User(TestResourceMixin, vms.User):
    pass


class Volume(TestResourceMixin, vms.Volume):
    pass


class BlockHost(TestResourceMixin, vms.BlockHost):
    pass


class BlockHostMapping(TestResourceMixin, vms.BlockHostMapping):
    pass


class ProtectionPolicy(TestResourceMixin, vms.ProtectionPolicy):
    pass


class ProtectedPath(TestResourceMixin, vms.ProtectedPath):
    pass


class Cluster(TestResourceMixin, vms.Cluster):
    @property
    def is_loopback(self) -> bool:
        """Loopback VAST exposes S3 on 9090 instead of 80."""
        clusters = self.list()
        if not clusters:
            return False
        name = str(getattr(clusters[0], "name", "") or "").lower()
        return "loop" in name

    def ensure_trash_state(self, enabled: bool, resilient_to_s3_versioning: bool = False) -> bool:
        """Enable or disable the cluster-wide trash folder (NFS volume delete)."""
        clusters = self.list()
        if not clusters:
            raise RuntimeError(f"No VAST cluster records at {self.session.endpoint}")
        cluster = clusters[0]
        if bool(getattr(cluster, "enable_trash", False)) == bool(enabled):
            logger.info(f"Trash folder already enabled={enabled} on cluster {cluster.id}")
            return True
        try:
            self.update(cluster.id, enable_trash=enabled)
        except ApiError as exc:
            body = (getattr(exc.response, "text", None) or str(exc)).lower()
            if (
                resilient_to_s3_versioning
                and getattr(exc.response, "status_code", None) == 503
                and "unable to enable trash folder while there are views with s3 versioning enabled" in body
            ):
                logger.warning("trash couldn't be enabled due to existing views with s3 versioning")
                return False
            raise
        wait(
            10,
            lambda: bool(getattr(self.get(cluster.id), "enable_trash", False)) == bool(enabled),
            sleep=1,
            message=f"failed ensuring trash folder enabled={enabled} on {self.session.endpoint}",
        )
        logger.info(f"Trash folder was globally enabled={enabled} on {self.session.endpoint}")
        return True
