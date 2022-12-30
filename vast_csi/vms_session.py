import os
import json
import requests
from pprint import pformat
from typing import ClassVar

from easypy.bunch import Bunch
from easypy.caching import cached_property
from easypy.collections import shuffled
from easypy.misc import at_least
from easypy.tokens import (
    ROUNDROBIN,
    RANDOM,
    CONTROLLER_AND_NODE,
    CONTROLLER,
    NODE,
)
from plumbum import cmd
from plumbum import local, ProcessExecutionError

from .logging import logger
from .configuration import Config
from .exceptions import ApiError, MountFailed
from .utils import parse_load_balancing_strategy
from . import csi_types as types


class RESTSession(requests.Session):
    def __init__(self, *args, auth, base_url, ssl_verify, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.ssl_verify = ssl_verify
        self.auth = auth
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"
        self.config = Config()

    def request(self, verb, api_method, *args, params=None, log_result=True, **kwargs):
        verb = verb.upper()
        api_method = api_method.strip("/")
        url = [self.base_url, api_method]
        url.extend(args)
        url += [""]  # ensures a '/' at the end
        url = "/".join(str(p) for p in url)
        logger.info(f">>> [{verb}] {url}")

        if "data" in kwargs:
            kwargs["data"] = json.dumps(kwargs["data"])

        if params or kwargs:
            for line in pformat(dict(kwargs, params=params)).splitlines():
                logger.info(f"    {line}")

        ret = super().request(
            verb, url, verify=self.ssl_verify, params=params, **kwargs
        )

        if ret.status_code in (400, 503):
            raise ApiError(response=ret)
        ret.raise_for_status()

        logger.info(f"<<< [{verb}] {url}")
        if ret.content:
            ret = Bunch.from_dict(ret.json())
            if log_result:
                for line in pformat(ret).splitlines():
                    logger.info(f"    {line}")
            else:
                size = len(ret) if isinstance(ret, (dict, tuple, list, str)) else '-'
                logger.info(f"{type(ret)[{size}]}")
        else:
            ret = None
        logger.info(f"--- [{verb}] {url}: Done")
        return ret

    def __getattr__(self, attr):
        if attr.startswith("_"):
            raise AttributeError(attr)

        def func(*args, log_result=True, **params):
            return self.request("get", attr, *args, params=params, log_result=log_result)

        func.__name__ = attr
        func.__qualname__ = f"{self.__class__.__qualname__}.{attr}"
        setattr(self, attr, func)
        return func


class VmsSession(RESTSession):
    """
    Communication with vms cluster.
    Operations over vip pools, quotas, snapshots etc.
    """

    _vip_round_robin_idx: ClassVar[int] = -1

    # ----------------------------
    # Clusters
    @property
    def cluster(self) -> Bunch:
        """Get cluster info"""
        return Bunch.from_dict(self.clusters()[0])

    def delete_folder(self, path: str):
        """Delete remote cluster folder by provided path."""
        try:
            self.delete(f"/clusters/{self.cluster.id}/delete_folder/", json={"path": path})
        except ApiError as e:
            if "no such directory" in e.render():
                logger.debug(f"remote folder was probably already deleted ({e})")
            else:
                raise

    # ----------------------------
    # View policies
    def get_policy_by_name(self, policy_name: str):
        """
        Get view policy by name.
        Returns: None if policy doesn't exist.
        """
        if res := self.viewpolicies(name=policy_name):
            return Bunch.from_dict(res[0])

    def ensure_view_policy(self, policy_name: str):
        """Check if view policy exists on remote cluster and if not create new policy with provided name."""
        if (policy := self.get_policy_by_name(policy_name)) is None:
            raise Exception(f"No such policy: {policy_name}. Please create policy manually")
        return policy

    # ----------------------------
    # Views
    def get_view_by_path(self, path):
        """
        Get list of views that contain provided path.
        If there is no view for specific path empty list will be returned.
        """
        return self.views(path=path)

    def create_view(self, path: str, policy_id: int, create_dir: bool = True):
        """
        Create new view on remove cluster
        Args:
            path: full system path to create view for.
            policy_id: id of view policy that should be assigned to view.
            create_dir: if underlying directory should be created along with view.
        Returns:
            newly created view as dictionary.
        """
        data = {
            "path": path,
            "create_dir": create_dir,
            "protocols": ["NFS"],
            "policy_id": policy_id
        }
        return self.post("views", data)

    def delete_view(self, path: str):
        """Delete view by provided path criteria."""
        if res := self.views(path=path):
            self.delete(f"views/{res[0]['id']}")

    # ----------------------------
    # Vip pools
    def get_vip(self, vip_pool_name: str, load_balancing: str = None):
        """
        Get vip pool by provided id.
        Returns:
            One of ips from provided vip pool according to provided load balancing strategy.
        """
        load_balancing = parse_load_balancing_strategy(load_balancing or self.config.load_balancing)
        vips = [vip for vip in self.vips(log_result=False) if vip.vippool == vip_pool_name]
        if not vips:
            raise Exception(f"No vips in pool {vip_pool_name}")

        if load_balancing == ROUNDROBIN:
            self._vip_round_robin_idx = (self._vip_round_robin_idx + 1) % len(vips)
            vip = vips[self._vip_round_robin_idx]
        elif load_balancing == RANDOM:
            vip = shuffled(vips)[0]
        else:
            raise Exception(
                f"Invalid load_balancing mode: '{load_balancing}'"
            )

        logger.info(
            f"Using {load_balancing} - chose {vip.title}, currently connected to {vip.cnode}"
        )
        return vip.ip

    # ----------------------------
    # Quotas
    def list_quotas(self, max_entries) -> Bunch:
        """List of quotas"""
        return self.quotas(page_size=max_entries)

    def create_quota(self, data):
        """Create new quota"""
        return self.post("quotas", data=data)

    def get_quota(self, volume_id):
        """Get quota by volume id."""
        quotas = self.quotas(path__contains=volume_id)
        if not quotas:
            return
        elif len(quotas) > 1:
            names = ", ".join(sorted(q.name for q in quotas))
            raise Exception(f"Too many quotas on {volume_id}: {names}")
        else:
            return quotas[0]

    def get_quotas_by_path(self, path):
        path = path.rstrip("/")
        return self.quotas(path=path)

    def update_quota(self, quota_id, data):
        """Update existing quota."""
        self.patch(f"quotas/{quota_id}", data=data)

    def delete_quota(self, quota_id):
        """Delete quota"""
        self.delete(f"quotas/{quota_id}")

    # ----------------------------
    # Snapshots

    def snapshot_list(self, page_size):
        return self.snapshots(page_size=page_size)

    def has_snapshots(self, path):
        path = path.rstrip("/") + "/"
        ret = self.snapshots(path=path, page_size=10)  # we intentionally limit the number of results
        return ret.results

    def create_snapshot(self, data):
        """Create new snapshot."""
        return self.post("snapshots", data=data)

    def get_snapshot(self, snapshot_name=None, snapshot_id=None):
        """
        Get snapshot by name or by id.
        Only one argument should be provided.
        """
        if snapshot_name:
            ret = self.snapshots(name=snapshot_name)
            if len(ret) > 1:
                raise Exception(f"Too many snapshots named {snapshot_name}: ({len(ret)})")
            return ret[0]
        else:
            return self.snapshots(snapshot_id)

    def delete_snapshot(self, snapshot_id):
        self.delete(f"snapshots/{snapshot_id}")

    def get_by_token(self, token):
        """
        This method used to iterate over paginated resources (snapshots, quotas etc).
        Where after first request to resource list token for next page is returned.
        """
        return self.get(token)


class TestVmsSession(RESTSession):
    """RestSession simulation for sanity tests"""

    def create_fake_quota(self, volume_id):
        class FakeQuota:

            def __init__(self, volume_id):
                super().__init__()
                self._volume = types.Volume()
                self._volume_id = volume_id

            def __str__(self):
                return "<< FakeQuota >>"

            def __getattr__(self, item):
                return getattr(self._volume, item)

            @property
            def id(self):
                return self

            @property
            def path(self):
                return local.path(os.environ["X_CSI_NFS_EXPORT"])[self._volume_id]

            @property
            def hard_limit(self):
                return 1000

        return FakeQuota(volume_id=volume_id)

    def _mount(self, src, tgt, flags=""):
        executable = cmd.mount
        flags = [f.strip() for f in flags.split(",")]
        flags += "port=2049,nolock,vers=3".split(",")
        executable = executable["-o", ",".join(flags)]
        try:
            executable[src, tgt] & logger.pipe_info("mount >>")
        except ProcessExecutionError as exc:
            if exc.retcode == 32:
                raise MountFailed(detail=exc.stderr, src=src, tgt=tgt)
            raise

    def _to_mock_volume(self, vol_id):
        vol_dir = self._mock_mount[vol_id]
        logger.info(f"{vol_dir}")
        if not vol_dir.is_dir():
            logger.info(f"{vol_dir} is not dir")
            return
        with self.config.fake_quota_store[vol_id].open("rb") as f:
            vol = self.create_fake_quota(volume_id=vol_id)
            vol.ParseFromString(f.read())
            return vol

    @cached_property
    def _mock_mount(self):
        target_path = self.config.controller_root_mount
        if not target_path.exists():
            target_path.mkdir()

        if not os.path.ismount(target_path):
            mount_spec = f"{self.config.nfs_server}:{self.config.sanity_test_nfs_export}"
            self._mount(
                mount_spec,
                target_path,
                flags=",".join(self.config.mount_options),
            )
            logger.info(f"mounted successfully: {target_path}")

        return target_path

    def get_vip(self, *_, **__) -> str:
        return self.config.nfs_server

    def get_quota(self, volume_id: str) -> "FakeQuota":
        """Create fake quota object which can simulate attributes of original Quota butch."""
        return self._to_mock_volume(volume_id)

    def delete_quota(self, quota: "FakeQuota"):
        """
        Delete all folders and files under '/csi-volumes/<volume id>
        Normally in this method quota id should be passed but here we abuse first position argument to
        pass FakeQuota which were initialized before and has '_volume_id' attribute.
        """
        self.config.controller_root_mount[quota._volume_id].delete()
        self.config.fake_quota_store[quota._volume_id].delete()

    def list_quotas(self, starting_token=None, max_entries=None):
        """
        This method simulates behaviour of list_quotas but instead requesting quotas from remote cluster
        it gets list of local volumes that were created before.
        """
        fields = Bunch.from_dict({
            "next_token": None,
            "results": []
        })

        starting_inode = int(starting_token) if starting_token else 0
        vols = (d for d in os.scandir(self._mock_mount) if d.is_dir())
        vols = sorted(vols, key=lambda d: d.inode())
        logger.info(f"Got {len(vols)} volumes in {self._mock_mount}")
        start_idx = 0

        logger.info(f"Skipping to {starting_inode}")
        for start_idx, d in enumerate(vols):
            if d.inode() > starting_inode:
                break

        del vols[:start_idx]

        remain = 0
        if max_entries:
            remain = at_least(0, len(vols) - max_entries)
            vols = vols[:max_entries]

        if remain:
            fields.next_token = str(vols[-1].inode())

        fields.results = [self._to_mock_volume(vol.name) for vol in vols]
        return fields

    def get_by_token(self, token):
        return self.list_quotas(starting_token=token)

    def _empty(self, *_, **__):
        """
        empty method for test scenarios
        Method needs to be declared for compatibility with sanity tests.
        """
        pass

    update_quota = _empty
    delete_view = _empty
    delete_folder = _empty
    get_view_by_path = _empty
