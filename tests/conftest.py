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
    return local.path(tmpdir)

@pytest.fixture
def vms_session(monkeypatch, mock_credentials):
    from vast_csi.plugins.base import get_vms_session
    from vast_csi.configuration import Config

    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
    with patch("vast_csi.vms_session.VmsSession.refresh_auth_token", MagicMock()):
        get_vms_session.cache_clear()
        yield get_vms_session()


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
            setattr(resource_val, method, MagicMock(return_value=retvalue))
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
