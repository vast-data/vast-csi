"""
Test VMS Session for unit testing and local development.

This module provides TestVmsSession which mocks VMS API interactions
for testing purposes.
"""

import os
import inspect
from unittest.mock import create_autospec, Mock
from contextlib import contextmanager

from easypy.bunch import Bunch
from easypy.caching import cached_property
from plumbum import cmd, local, ProcessExecutionError

from ..logging import logger
from ..exceptions import MountFailed
from .. import csi_types as types
from .base import RESTSession
from .resources import VastResource
from .vms_session import VmsSession

class TestVmsSession(RESTSession):
    """
    Initializes a TestVmsSession instance, which simulates the behavior of an original VmsSession
    with all its sub-resources and methods.

    This TestVmsSession creates a full spec of the original VmsSession, including all of its sub-resources
    (e.g., resources like `quotas`, `views`, `viewpolicies`, etc.) and methods.

    All methods of the sub-resources are mocked to return `None` by default. However, if the TestVmsSession
    contains special methods in the format `<subresource_name>_<subresource_method>`, these methods are
    treated as side effects. When called, these side-effect methods will override the default `None` return
    value, and their return value will be used as the return value of the mocked method.

    This behavior is useful for testing scenarios where interactions with the `VmsSession` and its resources
    need to be simulated without actually invoking the underlying operations.
    """

    # Identity-based hash/eq so each TestVmsSession instance is treated as a unique
    # session by the dogpile.cache key generator (same semantics as object default,
    # but explicit to survive any future __eq__ additions to base classes).
    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __init__(self, config):
        from unittest.mock import create_autospec, Mock

        super().__init__(config)
        vms_session = VmsSession(config, *[None] * 7)
        own_attributres = dir(self)
        for resource in dir(vms_session):
            if resource.startswith("_"):
                continue
            value = getattr(vms_session, resource)
            if callable(value) and not resource in own_attributres:
                setattr(self, resource, value)
            elif isinstance(value, VastResource):
                spec = Mock(spec=value, name=resource)
                for name, method in inspect.getmembers(value, predicate=callable):
                    # special method name to override default behavior
                    own_override_property = f"{resource}_{name}"
                    if name.startswith("_"):
                        continue
                    elif own_override_property in own_attributres:
                        setattr(spec, name, create_autospec(method, side_effect=getattr(self, own_override_property)))
                    else:
                        setattr(spec, name, create_autospec(method, return_value=None))
                setattr(self, resource, spec)


    @classmethod
    def create(cls, config, *_, **__):
        return cls(config)

    def create_fake_quota(self, volume_id):
        class FakeQuota:

            def __init__(self, volume_id):
                super().__init__()
                self._volume = types.Volume()
                self._volume_id = volume_id
                self.tenant_id = 1
                self.tenant_name = "test-tenant"

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
            raise MountFailed(detail=exc.stderr, src=src, tgt=tgt)

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

    def vippools_get_vip(self, *_, **__) -> str:
        return self.config.nfs_server

    def quotas_one(self, name: str) -> "FakeQuota":
        """Create fake quota object which can simulate attributes of original Quota butch."""
        return self._to_mock_volume(name)

    def quotas_delete(self, quota: "FakeQuota"):
        """
        Delete all folders and files under '/csi-volumes/<volume id>
        Normally in this method quota id should be passed but here we abuse first position argument to
        pass FakeQuota which were initialized before and has '_volume_id' attribute.
        """
        self.config.controller_root_mount[quota._volume_id].delete()
        self.config.fake_quota_store[quota._volume_id].delete()

    @contextmanager
    def views_temp_view(self, path, policy_id, tenant_id):
        yield Bunch(
            id=1,
            alias=path,
            tenant_id=tenant_id,
            tenant_name="test-tenant"
        )

    def views_one(self, *_, **__):
        return Bunch(id=1, policy_id=1, tenant_id=1)

    def viewpolicies_one(self, *_, **__):
        return Bunch(id=1, tenant_id=1, tenant_name="test-tenant")

    def snapshots_list(self, *_, **__):
        return []
