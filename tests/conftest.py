import sys
import inspect
from pathlib import Path
from tempfile import gettempdir
from typing import List, Optional
from unittest.mock import  MagicMock, patch

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
# Extend python import path to get vast_csi package from here
sys.path += [ROOT.as_posix()]

with local.cwd(gettempdir()) as tempdir:
    # Temporary change working directory and create version.info file in order to allow reading
    # driver name, version and git commit by Config.
    tempdir["version.info"].open("w").write("csi.vastdata.com v0.0.0 #### local")
    from vast_csi.plugins.csi import CsiController, CsiNode, Config
    from vast_csi.plugins.cosi import CosiProvisioner
    from vast_csi.plugins.block import BlockController, BlockNode
    import vast_csi.csi_types as types

# Restore original methods on Controller and Node in order to get rid of Instrumented logging layer.
for cls in (CsiController, CsiNode, CosiProvisioner, BlockController, BlockNode):
    for name, _ in inspect.getmembers(cls.__base__, inspect.isfunction):
        if name.startswith("_"):
            continue
        func = getattr(cls, name)
        setattr(cls, name, func.__wrapped__)
        # Simulate getting __wrapped__ context from function. This logic is used in csi driver so tests should also
        # support this.
        setattr(func, "__wrapped__", func.__wrapped__)


# Load configuration
CONF = Config()
for pkg_name in ("vast_csi.plugins.csi", "vast_csi.plugins.cosi",  "vast_csi.plugins.block"):
    if module := sys.modules.get(pkg_name):
        module.CONF = CONF


# ----------------------------------------------------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def mock_credentials(tmpdir):
    """Fixture to mock the credentials files"""
    tmpdir.join("username").write("test")
    tmpdir.join("password").write("test")
    tmpdir.join("endpoint").write("mock.test.com")
    tmpdir.join("passphrase").write("test_passphrase")
    return local.path(tmpdir)

@pytest.fixture
def vms_session(monkeypatch, mock_credentials):
    from vast_csi.plugins.base import get_vms_session
    from vast_csi.configuration import Config

    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
    with patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock()):
        get_vms_session.cache_clear()
        yield get_vms_session()


@pytest.fixture(autouse=True)
def clear_lru_cache():
    """
    Clear the LRU cache before each test to prevent stale cached values
    from interfering with mocked methods.
    """
    from vast_csi.lru_cache import _cache_region
    # Clear the cache before each test
    _cache_region.backend._cache.clear()
    yield
    # Optionally clear after test as well
    _cache_region.backend._cache.clear()


@pytest.fixture
def vms_session_with_mocked_resources_factory(vms_session):
    """Factory vms session with mocked sub resources."""

    def __wrapped(*args):
        """
        args must be tuple where first item is resource name (for instance quotas),
        second is method to mock and third item is return value
        """
        for resource, method, retvalue in args:
            resource_val = getattr(vms_session, resource)
            mock = MagicMock(return_value=retvalue)
            setattr(resource_val, method, mock)
            
            # If mocking "one" method, also mock "one_cached" for resources that have it
            if method == "one" and hasattr(resource_val, "one_cached"):
                setattr(resource_val, "one_cached", mock)
            
            # If mocking "ensure" method, also mock "ensure_cached" for resources that have it
            if method == "ensure" and hasattr(resource_val, "ensure_cached"):
                setattr(resource_val, "ensure_cached", mock)
        return vms_session

    return __wrapped


@pytest.fixture
def volume_capabilities():
    """Factory for building VolumeCapabilities with either block or mount access types."""

    def __wrapped(
        mode: str,  # Required field
        access_type: Optional[str] = "mount",  # Optional, default to 'mount'
        fs_type: Optional[str] = None,  # Optional, only for mount
        mount_flags: Optional[List[str]] = None,  # Optional, only for mount
        volume_mount_group: Optional[str] = None,  # Optional, only for mount
    ) -> List[types.VolumeCapability]:
        if isinstance(mount_flags, str):
            mount_flags = [mount_flags]
        if access_type == "block":
            return [
                types.VolumeCapability(
                    block=types.BlockVolume(),  # Intentionally empty
                    access_mode=types.AccessMode(mode=mode),
                )
            ]
        elif access_type == "mount":
            return [
                types.VolumeCapability(
                    mount=types.MountVolume(
                        fs_type=fs_type or "",
                        mount_flags=mount_flags or [],
                        volume_mount_group=volume_mount_group or "",
                    ),
                    access_mode=types.AccessMode(mode=mode),
                )
            ]
        else:
            raise ValueError("Invalid access_type. Must be 'block' or 'mount'.")

    return __wrapped
