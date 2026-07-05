"""
Base session classes and utilities for VAST CSI VMS communication.

This module contains the core RESTSession implementation, decorators,
and helper functions for session management.
"""

import re
import json
import inspect
import requests
from types import FunctionType
from functools import wraps
from pprint import pformat
from requests import cookies
from requests.utils import default_user_agent

from easypy.bunch import Bunch
from easypy.semver import SemVer
from easypy.caching import locking_cache
from easypy.resilience import retrying

from ..logging import logger
from ..configuration import Config
from ..exceptions import ApiError, OperationNotSupported, LookupFieldError
from ..serialization_utils import SerializationMixin


class ApiVersion:
    """Decorator factory for API version specification."""
    
    VALID_VERSION_PATTERN = re.compile(r"^v\d+$")  # Matches "v" followed by one or more digits

    def __getattr__(self, ver):
        if not self.VALID_VERSION_PATTERN.match(ver):
            raise ValueError(
                f"Invalid API version: {ver}. Must match pattern '{self.VALID_VERSION_PATTERN.pattern}'"
            )

        def dec(target):
            if isinstance(target, FunctionType):
                return self._decorate_function(target, ver)
            elif isinstance(target, type):
                return self._decorate_class(target, ver)
            else:
                raise TypeError(f"Unsupported target type: {type(target).__name__}")

        return dec

    def _decorate_function(self, func, ver):
        """Decorate a function by injecting the `api_ver` argument."""
        @wraps(func)
        def wrapper(*args, **kwargs):
            sig = inspect.signature(func)
            if "api_ver" in sig.parameters:
                kwargs["api_ver"] = ver  # Add `api_ver` to kwargs if it exists in parameters
            elif any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()):
                kwargs["api_ver"] = ver  # Inject `api_ver` into `**kwargs` if available

            return func(*args, **kwargs)
        return wrapper

    def _decorate_class(self, cls, ver):
        """Decorate all methods of a class, including inherited ones."""
        for attr_name, attr_val in inspect.getmembers(cls, predicate=callable):
            if attr_name.startswith("_"):
                continue
            if isinstance(attr_val, FunctionType):
                decorated_method = self._decorate_function(attr_val, ver)
                setattr(cls, attr_name, decorated_method)
        return cls


# Global API version decorator instance
apiver = ApiVersion()


def requisite(semver: str, operation: str = None, ignore: bool = False):
    """
    Use this decorator to indicate the minimum required version of the VAST cluster
     for invoking the API that is being decorated.
    Decorator works in two modes:
    1. When ignore == False and version mismatch detected then `OperationNotSupported` exception will be thrown
    2. When ignore == True and version mismatch detected then method decorated method execution never happened
    """
    required_version = SemVer.loads_fuzzy(semver)

    def dec(fn):

        def _args_wrapper(self, *args, **kwargs):

            sw_version = self.session.versions.get_sw_version()
            if sw_version < required_version:
                if ignore:
                    return
                raise OperationNotSupported(
                    op=operation or fn.__name__,
                    required_version=required_version.dumps(),
                    current_version=sw_version.dumps(),
                    tip="Upgrade VAST cluster or adjust CSI driver settings to avoid unsupported operations"
                )
            return fn(self, *args, **kwargs)

        return _args_wrapper

    return dec


class CannotUseTrashAPI(OperationNotSupported):
    """Exception raised when trash API cannot be used."""
    template = "Cannot delete folder via VMS: {reason}"


def instantiate_session_from_secret(secret_kwargs: dict, key_prefix: tuple = ("",)):
    """
    Instantiate a VMS session from secret parameters with prefix fallback support.

    Args:
        secret_kwargs: Dictionary of secret parameters
        key_prefix: Tuple of prefixes to try in order. For example:
                    ("src_", "") will try "src_username" first, then "username"
                    ("secondary_",) will only try "secondary_username"
                    ("",) (default) will only try "username"

    Returns:
        VmsSession instance

    Raises:
        LookupFieldError: If session cannot be instantiated with any of the prefixes
    """
    vms_session_args = inspect.signature(get_vms_session).parameters.keys()

    # Try each prefix in order
    last_error = None
    for prefix in key_prefix:
        try:
            session_kwargs = {k: secret_kwargs.get(prefix + k) for k in vms_session_args}
            return get_vms_session(**session_kwargs)
        except LookupFieldError as e:
            last_error = e
            # Continue to try next prefix
            continue

    # All prefixes failed, raise the last error
    if last_error:
        raise last_error
    else:
        raise LookupFieldError(field="session from secret prefixes")


@locking_cache
def get_vms_session(username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None):
    """
    Factory function to create and cache VMS sessions.
    
    Returns either a real VmsSession or TestVmsSession based on configuration.
    """
    # Import here to avoid circular dependency
    from .vms_session import VmsSession
    from .test_session import TestVmsSession
    
    config = Config()
    session_cls = TestVmsSession if config.mock_vast else VmsSession
    return session_cls.create(
        config=config, username=username, password=password, token=token,
        tenant=tenant, endpoint=endpoint, ssl_cert=ssl_cert, cluster_name=cluster_name,
    )


class NoCookiesJar(cookies.RequestsCookieJar):
    """Cookie jar that doesn't actually store cookies."""
    
    def set(self, name, value, **kwargs):
        return None

    def set_cookie(self, cookie, *args, **kwargs):
        return


class RESTSession(requests.Session):
    """
    Base REST session for HTTP communication with VAST VMS API.
    
    This class extends requests.Session with:
    - Automatic token refresh
    - Request logging
    - Error handling
    - Usage reporting
    """
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.cookies = NoCookiesJar()
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"
        self.headers["User-Agent"] = f"VastCSI/{config.plugin_version}.{config.ci_pipe}.{config.git_commit[:10]} ({config._mode.capitalize()}) {default_user_agent()}"
        self.headers['authorization'] = ""  # will be set on first request

    @retrying.debug(times=3, acceptable=retrying.Retry)
    def request(self, verb, api_method, *args, params=None, log_result=True, api_ver=None, **kwargs):
        if not self.headers.get("authorization"):
            self.refresh_auth_token()

        verb = verb.upper()
        api_method = api_method.strip("/")
        api_ver = api_ver or "v1"
        # If api_method already starts with the api version (e.g. "v1/snapshots/..."),
        # don't prepend it again — this happens with pagination URLs.
        if api_method.startswith(f"{api_ver}/"):
            api_method = api_method[len(api_ver) + 1:]  # strip "vN/"
        base_url = f"{self.base_url}/{api_ver}"
        url = [base_url, api_method]
        url.extend(args)
        url += [""]  # ensures a '/' at the end
        url = "/".join(str(p) for p in url)
        logger.info(f">>> [{verb}] {url}")

        if "data" in kwargs:
            kwargs["data"] = json.dumps(kwargs["data"])

        if params or kwargs:
            if log_result:
                for line in pformat(dict(kwargs, params=params)).splitlines():
                    logger.info(f"    {line}")
            else:
                logger.info("*** request payload is hidden ***")

        kwargs.setdefault("timeout", self.config.timeout)

        ret = super().request(
            verb, url, verify=self.ssl_verify, params=params, **kwargs
        )
        if not self.token and ret.status_code == 403:
            self.refresh_auth_token()
            raise retrying.Retry("refresh token")

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
        
        # Opportunistically send usage stats after successful requests
        if not self.config.disable_usage_stats and not url.endswith('/plugins/usage/'):
            self.plugins.usage_report()
        
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
