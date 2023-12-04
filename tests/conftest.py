import sys
import inspect
from pathlib import Path
from tempfile import gettempdir
from contextlib import contextmanager
from typing import List, Optional, Any
from unittest.mock import patch, MagicMock

import pytest
from plumbum import local
from easypy.aliasing import aliases
from easypy.bunch import Bunch

ROOT = Path(__file__).resolve().parents[1]
# Extend python import path to get vast_csi package from here
sys.path += [ROOT.as_posix()]

with local.cwd(gettempdir()) as tempdir:
    # Temporary change working directory and create version.info file in order to allow reading
    # driver name, version and git commit by Config.
    tempdir["version.info"].open("w").write("csi.vastdata.com v0.0.0 #### local")
    from vast_csi.server import Controller, Node, Config
    import vast_csi.csi_types as types

# Restore original methods on Controller and Node in order to get rid of Instrumented logging layer.
for cls in (Controller, Node):
    for name, _ in inspect.getmembers(cls.__base__, inspect.isfunction):
        if name.startswith("_"):
            continue
        func = getattr(cls, name)
        setattr(cls, name, func.__wrapped__)
        # Simulate getting __wrapped__ context from function. This logic is used in csi driver so tests should also
        # support this.
        setattr(func, "__wrapped__", func.__wrapped__)

# Load configuration
import vast_csi.server

vast_csi.server.CONF = Config()


# ----------------------------------------------------------------------------------------------------------------------
# Helper classes and decorators
# ----------------------------------------------------------------------------------------------------------------------


class FakeQuota:
    """Simulate quota attributes"""

    def __init__(self, hard_limit: int, quota_id: int, tenant_id):
        self._hard_limit = hard_limit
        self._id = quota_id
        self.tenant_id = tenant_id

    @property
    def id(self):
        return self._id

    @property
    def hard_limit(self):
        return self._hard_limit


@aliases("mock", static=False)
class FakeSessionMethod:
    """
    Method of FakeSession that enhances all methods of decorated class with
    MagicMock capabilities eg: 'assert_called', 'call_args', 'assert_called_with' etc.
    """

    def __init__(self, return_value: Optional = None, return_condition: Optional[bool] = True):
        # Mock to stare all execution calls
        self.mock = MagicMock()
        self.return_value = return_value
        self.return_condition = return_condition

    def __call__(self, *args, **kwargs) -> Any:
        self.mock(*args, **kwargs)
        if self.return_condition:
            return self.return_value


class FakeSession:
    """Simulate VAST session behavior"""

    def __init__(self,
                 view: Optional[Bunch] = Bunch(path="/test/view", id=1, tenant_id=1),
                 quota_id: Optional[int] = 1,
                 quota_hard_limit: Optional[int] = 1000
                 ):
        """
        Args:
            view: Returned view path by 'get_view_by_path' method.
                Use this variable to control returned view. Specify None to simulate 'view doesn't exist` behavior
            quota_id: Id of returned quota by 'get_quota' method
            quota_hard_limit: Hard limit of quota returned by 'get_quota' method
                Use this variable to control returned quota. Specify None to simulate 'quota doesn't exist` behavior
        """
        self.view = view
        self.quota_id = quota_id
        self.quota_hard_limit = quota_hard_limit

        # Methods declaration
        self.get_quota = FakeSessionMethod(
            return_value=FakeQuota(self.quota_hard_limit, self.quota_id, tenant_id=1),
            return_condition=self.quota_hard_limit is not None)
        self.get_view_by_path = FakeSessionMethod(return_value=self.view)
        self.ensure_view = FakeSessionMethod(return_value=self.view)


# ----------------------------------------------------------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def volume_capabilities():
    """Factory for building VolumeCapabilities"""

    def __wrapped(
            fs_type: str, mount_flags: str, mode: types.AccessModeType
    ) -> List[types.VolumeCapability]:
        return [
            types.VolumeCapability(
                mount=types.MountVolume(fs_type=fs_type, mount_flags=mount_flags),
                access_mode=types.AccessMode(mode=mode),
            )
        ]

    return __wrapped


@pytest.fixture
def fake_session():
    """
    FakeSession factory.
    Use this fixture as context manager to mock original vms session.
    """

    @contextmanager
    def __wrapped(
            quota_id: Optional[int] = 1,
            quota_hard_limit: Optional[int] = 1000,
            view: Optional[str] = Bunch(path="/test/view", id=1, tenant_id=1)
    ):
        session_mock = FakeSession(view=view, quota_id=quota_id, quota_hard_limit=quota_hard_limit)
        with patch("vast_csi.server.Controller.vms_session", session_mock):
            yield session_mock

    yield __wrapped
