import os
import re
import json
import requests
import hashlib
import inspect
from abc import ABC
from pprint import pformat
from uuid import uuid4
from types import FunctionType
from contextlib import contextmanager
from datetime import datetime
from functools import wraps
from requests.exceptions import ConnectionError, HTTPError
from requests.utils import default_user_agent

from easypy.bunch import Bunch, bunchify
from easypy.caching import cached_property
from easypy.collections import shuffled
from easypy.semver import SemVer
from easypy.caching import timecache, locking_cache
from easypy.units import HOUR, MINUTE
from easypy.sync import wait
from easypy.resilience import retrying, resilient
from easypy.humanize import yesno_to_bool
from plumbum import cmd
from plumbum import local, ProcessExecutionError
from urllib3.exceptions import MaxRetryError, ReadTimeoutError, TimeoutError
from easypy.resilience import resilient as easypy_resilient

from .logging import logger
from .configuration import Config
from .exceptions import ApiError, MountFailed, OperationNotSupported, LookupFieldError, TaskFailed
from .utils import generate_ip_range
from . import csi_types as types
from .serialization_utils import SerializationMixin


class ApiVersion:
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
    template = "Cannot delete folder via VMS: {reason}"


@locking_cache
def get_vms_session(username=None, password=None, token=None, tenant=None, endpoint=None, ssl_cert=None, cluster_name=None):
    config = Config()
    session_cls = TestVmsSession if config.mock_vast else VmsSession
    return session_cls.create(
        config=config, username=username, password=password, token=token,
        tenant=tenant, endpoint=endpoint, ssl_cert=ssl_cert, cluster_name=cluster_name,
    )


class RESTSession(requests.Session):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"
        self.headers["User-Agent"] = f"VastCSI/{config.plugin_version}.{config.ci_pipe}.{config.git_commit[:10]} ({config._mode.capitalize()}) {default_user_agent()}"
        self.headers['authorization'] = f"Bearer #"  # will be updated on first request

    @retrying.debug(times=3, acceptable=retrying.Retry)
    def request(self, verb, api_method, *args, params=None, log_result=True, api_ver=None, **kwargs):
        verb = verb.upper()
        api_method = api_method.strip("/")
        api_ver = api_ver or "v1"
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

class VmsSession(RESTSession, SerializationMixin):
    """
    Communication with vms cluster.
    Operations over vip pools, quotas, snapshots etc.
    """
    def __init__(self, config, username, password, token, tenant, endpoint, ssl_cert, cluster_name):
        super().__init__(config)
        self.username = username
        self.password = password
        self.token = token
        self.tenant = tenant
        self.endpoint = endpoint
        self.ssl_cert = ssl_cert
        self.cluster_name = cluster_name  # for serialization
        self.base_url = f"https://{endpoint}/api"
        # Modify the SSL verification CA bundle path established
        # by the underlying Certifi library's defaults if ssl_verify==True.
        certs_base_dir = "/etc/ssl/certs"
        if ssl_cert:
            # Store the certificate specified in StorageClass secret (unique for each StorageClass)
            hash_obj = hashlib.sha256("".join([username, password, endpoint]).encode())
            unique_hash = hash_obj.hexdigest()
            cert_path = f"{certs_base_dir}/{endpoint}-{unique_hash}.crt"
            with open(cert_path, "w") as f:
                f.write(ssl_cert)
            logger.info(f"Generated new ssl certificate: {cert_path!r}")
        else:
            # Use certificate provided from global `sslCertsSecretName` secret (common for all StorageClasses)
            # This way requests library can use mounted CA bundle or default system CA bundle under the same path.
            cert_path = f"{certs_base_dir}/ca-certificates.crt"
        self.ssl_verify = (False, cert_path)[config.ssl_verify]

        if self.token:
            self.headers["Authorization"] = f"Api-Token {self.token}"
        if self.tenant:
            self.headers["X-Tenant-Name"] = self.tenant

        # Sub resources
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


    def dump_data(self) -> object:
        return {
            "username": self.username,
            "password": self.password,
            "token": self.token,
            "tenant": self.tenant,
            "endpoint": self.endpoint,
            "ssl_cert": self.ssl_cert,
            "cluster_name": self.cluster_name,
        }

    @staticmethod
    def load_data(data_fields: dict) -> "VmsSession":
        """
        Reconstruct an object from deserialized data fields.
        Args:
            data_fields: The result of unpickling the stored internal state.
        Returns:
            An instance of the VmsSession class.
        """
        return get_vms_session(**data_fields)

    @classmethod
    def create(cls, config, username, password, token, tenant, endpoint, ssl_cert, cluster_name):
        """
        Creates an instance of the session, initializing credentials based on provided arguments or configuration context.

        :param config: The configuration object containing credentials and settings.
        :param username: Optional; the username for authentication. If not provided, it will be sourced from the secret.
        :param password: Optional; the password for authentication. If not provided, it will be sourced from the secret.
        :param token: Optional; the token for authentication.
        :param tenant: Optional; the tenant name for tenant scoped authentication (tenant admin).
        :param endpoint: Optional; the endpoint URL. If not provided, it will be sourced from the secret or environment.
        :param ssl_cert: SSL certificate for secure connections.
        :param cluster_name: Optional; specifies the cluster name for multi-cluster authentication.

        The following behaviors apply:
        1. StorageClass Secret (Recommended): If `cluster_name` is not provided
           but username, password, and endpoint are passed as arguments,
           these are used as StorageClass-level credentials.

        2. Multi-Cluster Secret: If `cluster_name` is specified,
           credentials are pulled from a multi-cluster YAML configuration in the secret,
            where each top-level key represents a cluster.
            This secret should be mounted at `/opt/vms-auth/clusters`
            Example:
                ```
                cluster1:
                  username: user1
                  password: 111111
                  endpoint: clstr1.example.com
                cluster2:
                  token: xxxxxxxxxxxxxxxxxxxx
                  endpoint: clstr2.example.com
                  tenant: csi-tenant
                ```

        3. Global Secret (Deprecated): If neither `cluster_name` nor username/password arguments are provided,
         credentials are sourced from a global secret mounted at `/opt/vms-auth`.
          This global secret should contain `username` and `password` fields,
           with the `endpoint` provided via environment variables.
           Note: Using a global secret is deprecated; it is recommended to use StorageClass secrets.

        Returns:
            An initialized session object with SSL verification status logged.
        """
        if cluster_name:
            if not (cluster_auth_config := config.cluster_credentials.get(cluster_name)):
                raise LookupFieldError(field="cluster_name", tip="Make sure cluster name is present in secret.")
            username = cluster_auth_config.get("username")
            password = cluster_auth_config.get("password")
            token = cluster_auth_config.get("token")
            tenant = cluster_auth_config.get("tenant")
            endpoint = cluster_auth_config.endpoint
            config_source = f"multi-cluster auth configuration ({cluster_name=})"
        else:
            # The presence of the name ot token in the arguments already indicates
            # that we have a StorageClass scope secret at this point.
            # In other words, it's not a globally mounted secret. Other secret fields will be validated below.
            is_global = not (username or token)
            config_source = "mounted credentials (global secret)" if is_global else "StorageClass secret"
            if config.vms_credentials_store.exists() and is_global:
                username = config.vms_user
                password = config.vms_password
                token = config.vms_token
                tenant = config.vms_tenant
                endpoint = config.vms_host

        if not token:
            if not username:
                raise LookupFieldError(field="username", tip=f"Make sure username is present in {config_source}.")
            if not password:
                raise LookupFieldError(field="password", tip=f"Make sure password is present in {config_source}.")
        elif username or password:
            raise Exception("Provide either both 'username' and 'password', or a 'token', but not both.")
        if not endpoint:
            raise LookupFieldError(field="endpoint", tip=f"Make sure endpoint is present in {config_source}.")
        session = cls(
            config=config,
            username=username,
            password=password,
            token=token,
            tenant=tenant,
            endpoint=endpoint,
            ssl_cert=ssl_cert,
            cluster_name=cluster_name,
        )
        ssl_verification = "enabled" if session.ssl_verify else "disabled"
        tenant_scope = f" with tenant scope {tenant=}" if tenant else ""
        logger.info(f"VMS session has been instantiated from {config_source}{tenant_scope}. SSL verification {ssl_verification}.")
        return session

    def refresh_auth_token(self):
        try:
            resp = super(RESTSession, self).request(
                "POST", f"{self.base_url}/v1/token/", verify=self.ssl_verify, timeout=5,
                json={"username": self.username, "password": self.password}
            )
            resp.raise_for_status()
            token = resp.json()["access"]
            self.headers['authorization'] = f"Bearer {token}"
        except ConnectionError as e:
            raise ApiError(
                response=Bunch(
                    status_code=None,
                    text=f"The vms on the designated host {self.config.vms_host!r} "
                         f"cannot be accessed. Please verify the specified endpoint. "
                         f"origin error: {e}"
                ))
        self.plugins.usage_report()

    def wait_task(self, task, latest=False, start_timeout=0, verbose=True):
        """
        Waits for a specific task to start and complete execution, monitoring its progress
        and handling various failure scenarios.
        """
        task_id = None
        task_line = 0

        def is_task_started(task):
            if isinstance(task, int):
                return self.vtasks(task)
            elif isinstance(task, dict):
                if "async_task" in task:
                    task = task["async_task"]
                return bunchify(task)
            elif tasks := self.vtasks(name=task, log_result=False):
                if len(tasks) == 1:
                    [task] = tasks
                    return task
                elif latest:
                    return max(tasks, key=lambda t: t.id)
                else:
                    raise Exception(f"Too many tasks with name '{task}': {[t.id for t in tasks]}")
            return False

        def is_task_complete(task_id):
            nonlocal task_line
            task = self.vtasks(task_id, log_result=False)
            if verbose:
                for line in task.messages[task_line:]:
                    logger.info(line)
            task_line = len(task.messages)
            if task.state == 'COMPLETED':
                return task
            elif task.state == 'FAILED':
                raise Exception(f"Task {task_id}: {task.messages[-1]}")
            elif task.state != 'RUNNING':
                raise TaskFailed(task=task, name=task.name, id=task.id, reason=task.messages[-1])
            else:
                raise TaskFailed(task=task, name=task.name, id=task.id, reason="timeout")

        if start_timeout:
            is_task_started = easypy_resilient.debug(
                acceptable=(
                    MaxRetryError,
                    ReadTimeoutError,
                    TimeoutError,
                    ConnectionResetError,
                    ConnectionError,
                    BrokenPipeError
                ),
                msg="Failed to fetch VMS task", default=False)(is_task_started)

        task = wait(start_timeout, lambda: is_task_started(task), sleep=1, message=f"No such task found: {task}")
        task_id = task.id
        timeout = task.timeout_in_seconds + 10  # add a grace period
        return wait(timeout, lambda: is_task_complete(task_id), sleep=1, message=False)


class VastResource(ABC):
    resource_name = NotImplemented
    TARGET_STATE = NotImplemented
    FAILED_STATES = NotImplemented
    RUNNING_STATES = NotImplemented

    def __init__(self, session: VmsSession):
        self.session = session

    def list(self, api_ver=None, **params):
        """Get list of entries with optional filtering params"""
        return self.session.get(self.resource_name, api_ver=api_ver, params=params)

    def create(self, api_ver=None, **params):
        """Create new entry with provided params"""
        return self.session.post(self.resource_name, api_ver=api_ver, data=params)

    def update(self, _id, api_ver=None, **params):
        """Update entry by id with provided params"""
        return self.session.patch(f"{self.resource_name}/{_id}", api_ver=api_ver, data=params)

    def delete(self, api_ver=None, **params):
        """Delete entry by provided params. Skip if entry not found."""
        entry = self.one(api_ver=api_ver, **params)
        if not entry:
            resource = self.__class__.__name__.lower()
            serialized_params = json.dumps(params, separators=(",", ":"))
            logger.info(f"{resource!r} not found for params {serialized_params}, skipping delete")
            return
        return self.delete_by_id(entry.id, api_ver=api_ver)

    def delete_by_id(self, _id, api_ver=None, **params):
        """Delete entry by id"""
        return self.session.delete(f"{self.resource_name}/{_id}", api_ver=api_ver, **params)

    def one(self, fail_if_missing=False, api_ver=None, **params):
        """
        Retrieve a single entry by provided filter parameters.
        Raises exception If no entry is found and `fail_if_missing` is True,
        or if multiple entries are found.
        """
        entries = self.list(api_ver=api_ver, **params)
        resource = self.__class__.__name__.lower()
        if not entries:
            if fail_if_missing:
                serialized_params = json.dumps(params, separators=(",", ":"))
                raise Exception(f"No {resource!r} found for params {serialized_params}")
            return
        if len(entries) > 1:
            serialized_params = json.dumps(params, separators=(",", ":"))
            raise Exception(f"Too many '{resource}s' found for params {serialized_params}: {entries}")
        return entries[0]

    def ensure(self, name, api_ver=None, **params):
        """Ensure entry with provided name exists. Create if not found."""
        entry = self.one(name=name, api_ver=api_ver)
        if not entry:
            entry = self.create(name=name, api_ver=api_ver, **params)
        return entry

    def get(self, _id, api_ver=None):
        """Get single entry by id"""
        return self.session.get(f"{self.resource_name}/{_id}", api_ver=api_ver)

    def _wait_for_state(self, resource_id):
        """
        Wait for a resource to reach a specific state.
        
        Args:
            resource_id: The resource ID to wait for
        """

        def is_resource_in_target_state():
            state = self.get(resource_id).state
            if state == self.TARGET_STATE:
                logger.info(f"{self.resource_name} {resource_id} reached target state: {state}")
                return True
            elif state in self.FAILED_STATES:
                raise Exception(f"{self.resource_name} {resource_id} failed with state: {state}")
            elif state in self.RUNNING_STATES:
                logger.info(f"{self.resource_name} {resource_id} still running (state: {state})")
                return False
            else:
                logger.warning(f"Unknown {self.resource_name} state: {state}")
                return False
        
        timeout = self.session.config.timeout
        logger.info(f"Waiting for {self.resource_name} {resource_id} to reach state '{self.TARGET_STATE}' (timeout: {timeout}s)...")
        
        wait(timeout, is_resource_in_target_state, sleep=5, message=f"{self.resource_name} {resource_id} did not reach state '{self.TARGET_STATE}' within {timeout} seconds")


class Version(VastResource):
    resource_name = "versions"

    @timecache(HOUR)
    def get_sw_version(self) -> SemVer:
        """Get VMS software version."""
        versions = self.list(status="success")[0].sys_version
        return SemVer.loads_fuzzy(versions)

class Plugin(VastResource):
    resource_name = "plugins"

    @requisite(semver="5.2.0", ignore=True)
    @resilient.error(msg="failed to report usage to VMS")
    def usage_report(self):
        self.session.post(f"{self.resource_name}/usage/",
            data={
                "vendor": "vastdata",
                "name": "vast-csi",
                "version": self.session.config.plugin_version,
                "build": self.session.config.git_commit[:10]
            })

class ViewPolicy(VastResource):
    resource_name = "viewpolicies"


class QosPolicy(VastResource):
    resource_name = "qospolicies"


class Tenant(VastResource):
    resource_name = "tenants"


class View(VastResource):
    resource_name = "views"

    def ensure(self, path, protocols, view_policy, qos_policy, create_dir=True, qos_policy_id=None):
        if not (view := self.one(path=str(path), policy__name=view_policy)):
            view_policy = self.session.viewpolicies.one(name=view_policy, fail_if_missing=True)
            if qos_policy:
                qos_policy_id = self.session.quospolicies.one(name=qos_policy, fail_if_missing=True).id
            view = self.create(
                path=str(path),
                protocols=protocols,
                policy_id=view_policy.id,
                qos_policy_id=qos_policy_id,
                tenant_id=view_policy.tenant_id,
                create_dir=create_dir,
            )
        return view

    def ensure_s3view(self, bucket_name, root_export, **kwargs):
        if not (view := self.one(bucket=bucket_name)):
            view_policy = kwargs.pop("view_policy", "s3_default_policy")
            protocols = kwargs.pop("protocols", None) or []
            if protocols:
                protocols = [p.upper().strip() for p in protocols.split(",")]
            if "S3" not in protocols:
                protocols.append("S3")
            view_policy = self.session.viewpolicies.one(name=view_policy, fail_if_missing=True)
            policy_id = view_policy.id
            tenant_id = view_policy.tenant_id
            root_export = root_export.strip("/")
            path = f"/{root_export}/{bucket_name}" if root_export else f"/{bucket_name}"
            for key in kwargs.keys():
               if kwargs[key] in ("true", "false"):
                   kwargs[key] = yesno_to_bool(kwargs[key])
            if "SMB" in protocols:
                kwargs["share"] = os.path.basename(path)
            if "create_dir" not in kwargs:
                kwargs["create_dir"] = True
            view = self.create(
                bucket=bucket_name, bucket_owner=bucket_name, path=path,
                protocols=protocols, policy_id=policy_id, tenant_id=tenant_id,
                **kwargs
            )
        return view

    @contextmanager
    def temp_view(self, path, policy_id, tenant_id) -> Bunch:
        """
        Create temporary view with autogenerated alias and delite it on context manager exit.
        """
        view = self.create(path=path, policy_id=policy_id, tenant_id=tenant_id, alias=f"/{uuid4()}")
        try:
            yield view
        finally:
            self.delete_by_id(view.id)

    @requisite(semver="5.3.0")
    @timecache(5 * MINUTE)
    @apiver.v5
    def get_subsystem(self, subsystem, **params):
        """Get BLOCK type view by provided name."""
        view = self.one(name=subsystem, fail_if_missing=True, **params)
        assert "BLOCK" in view.protocols, f"View {view.name} is not a block volume"
        return view

    @requisite(semver="5.3.0")
    @timecache(5 * MINUTE)
    @apiver.v5
    def get_subsystem_by_id(self, _id, **params):
        """Get BLOCK type view by provided id."""
        view = self.get(_id, **params)
        assert "BLOCK" in view.protocols, f"View {view.name} is not a block volume"
        return view


class Folder(VastResource):
    resource_name = "folders"

    @requisite(semver="4.7.0", operation="delete_folder")
    def delete(self, path: str, tenant_id: int):
        """Delete remote cluster folder by provided path."""

        if self.session.config.dont_use_trash_api:
            # trash api usage is disabled by csi admin or trash api doesn't exist for cluster
            raise CannotUseTrashAPI(reason="Disabled by Vast CSI settings (see 'dontUseTrashApi' in your Helm chart)")
        try:
            self.session.delete(f"{self.resource_name}/delete_folder/", data={"path": path, "tenant_id": tenant_id})
        except ApiError as e:
            if "no such directory" in e.render():
                logger.info(f"Remote directory might have been removed earlier. ({e})")
            elif "trash folder disabled" in e.render():
                raise CannotUseTrashAPI(reason="Trash Folder Access is disabled (see Settings/Cluster/Features in VMS)")
            else:
                # unpredictable error
                raise


class VipPool(VastResource):
    resource_name = "vippools"

    @timecache(5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    # Vip pools
    def get_vip(self, vip_pool_name: str, tenant_id: int = None):
        """
        Get vip by provided vip_pool_name.
        tenant_id is optional argument for validation. tenant_id usually
        make sense only during volume deletion where deletionVipPool and deletionViewPolicy
        is used. For such case additional validation might help to troubleshoot
        tenant misconfiguration.
        Returns:
            Random vip ip from provided vip pool.
        """
        vippool = self.one(name=vip_pool_name, fail_if_missing=True)
        if isinstance(tenant_id, str):
            # for tenant_id passed as volume context.
            tenant_id = int(tenant_id)
        if tenant_id and vippool.tenant_id and vippool.tenant_id != tenant_id:
            raise Exception(
                f"Pool {vip_pool_name} belongs to tenant with id {vippool.tenant_id} but {tenant_id=} was requested"
            )
        vips = generate_ip_range(vippool.ip_ranges)
        assert vips, f"Pool {vip_pool_name} has no available vips"
        vip = shuffled(vips)[0]
        logger.info(f"Using - {vip}")
        return vip


class Quota(VastResource):
    resource_name = "quotas"

    def one(self, name=None, path=None, **kwargs):
        """Get quota by provided query params."""
        if name:
            kwargs.update(path__contains=name)
        elif path:
            path = path.rstrip("/") or "/"  # for root path
            kwargs.update(path=path)
        return super().one(**kwargs)

    def ensure(self, volume_id, view_path, tenant_id, requested_capacity=None):
        if quota := self.one(path=view_path, tenant_id=tenant_id):
            # Check if volume with provided name but another capacity already exists.
            if (
                requested_capacity
                and
                quota.hard_limit is not None
                and
                quota.hard_limit != requested_capacity
            ):
                raise Exception(
                    "Volume already exists with different capacity than requested "
                    f"({quota.hard_limit})")
            if quota.tenant_id != tenant_id:
                raise Exception(
                    "Volume already exists with different tenancy ownership "
                    f"({quota.tenant_name})")
        else:
            data = dict(
                name=volume_id,
                path=view_path,
                tenant_id=tenant_id
            )
            if requested_capacity:
                data.update(hard_limit=requested_capacity)
            quota = self.create(**data)
        return quota


class Snapshot(VastResource):
    resource_name = "snapshots"

    def has_snapshots(self, path):
        # we intentionally limit the number of results
        ret = self.list(path__contains=path.rstrip("/"), page_size=10)
        return ret.results

    def create(self, name, path, tenant_id, expiration_delta=None):
        """Create new snapshot."""
        data = dict(name=name, path=path, tenant_id=tenant_id)
        if expiration_delta:
            expiration_time = (datetime.utcnow() + expiration_delta).isoformat()
            data["expiration_time"] = expiration_time
        return super().create(**data)

    def ensure(self, name, path, tenant_id, expiration_delta=None):
        if snapshot := self.one(name=name):
            if snapshot.path.strip("/") != path.strip("/"):
                raise Exception(
                    f"Snapshot already exists, but the specified path {path}"
                    f" does not correspond to the path of the snapshot {snapshot.path}"
                )
        else:
            path = path.rstrip("/") + "/"
            snapshot = self.create(
                name=name,
                path=path,
                tenant_id=tenant_id,
                expiration_delta=expiration_delta,
            )
        return snapshot


    def clone_volume(self, snapshot_id, target_subsystem_id, target_volume_path):
        """
        Clone a snapshot to a target volume.
        This method creates a new volume by cloning an existing snapshot and associates it
        with the specified subsystem and volume path.
        """
        data = {"target_subsystem_id": target_subsystem_id, "target_volume_path": target_volume_path}
        return self.session.post(f"{self.resource_name}/{snapshot_id}/clone_volume/", data=data)

    def has_not_finished_streams(self, snapshot_id):
        """Check if there are any global snapshot streams associated with the given snapshot ID"""
        resp = self.session.globalsnapstreams.list(loanee_snapshot__id=snapshot_id, page_size=10)
        return any(s.status.get("state", "").lower() != "finished" for s in resp["results"])

class GlobalSnapshotStream(VastResource):
    resource_name = "globalsnapstreams"
    TARGET_STATE = "Completed"
    FAILED_STATES = ["Suspended"]
    RUNNING_STATES = ["Initializing", "Syncing", "Finalizing", "Active"]

    def stop_snapshot_stream(self, snapshot_stream_id):
        return self.session.patch(f"{self.resource_name}/{snapshot_stream_id}/stop")

    @requisite(semver="4.6.0", operation="create_globalsnapshotstream")
    def ensure(self, name, snapshot_id, tenant_id, destination_path, wait=False):
        if not (snapshot_stream := self.one(name=name)):
            data = dict(
                loanee_root_path=destination_path,
                name=name,
                enabled=True,
                loanee_tenant_id=tenant_id, # target tenant_id
            )
            snapshot_stream = self.session.post(f"snapshots/{snapshot_id}/clone/", data)
        
        if wait:
            self._wait_for_state(snapshot_stream.id)
        
        return snapshot_stream

    @requisite(semver="4.6.0")
    def wait_by_loanee_path(self, loanee_root_path):
        """
        Wait for a global snapshot stream to be created by its loanee root path.
        This helper is useful for block volumes where GSS stream creation is hidden
        and gss stream has no meaningful name to query it by.
        """
        snapshot_stream = self.one(loanee_root_path__startswith=loanee_root_path, fail_if_missing=True)
        self._wait_for_state(snapshot_stream.id)

    @requisite(semver="4.6.0", ignore=True)
    def ensure_snapshot_stream_deleted(self, **params):
        """
        Stop global snapshot stream in case it is not finished.
        Snapshots with expiration time will be deleted as soon as snapshot stream is stopped.
        """
        if snapshot_stream := self.one(**params):
            state = snapshot_stream.status.get("state", "").lower()
            if state != "finished":
                logger.debug(f"Stopping snapshot stream {snapshot_stream.id} in state {state}")
                task = self.stop_snapshot_stream(snapshot_stream.id)
                self.session.wait_task(task)
            try:
                self.delete_by_id(_id=snapshot_stream.id, data={"remove_dir": True})
            except HTTPError as e:
                if e.response.status_code == 404:
                    # Ignore 404 error if snapshot stream is already deleted
                    # because it might happen if the stream was deleted by another process (csi worker)
                    logger.warning(f"Snapshot stream {snapshot_stream.id} already deleted")
                else:
                    raise


class User(VastResource):
    resource_name = "users"

    def generate_access_key(self, _id):
        return self.session.post(f"{self.resource_name}/{_id}/access_keys/", log_result=False)

    def delete_access_key(self, _id, access_key):
        data = dict(access_key=access_key)
        return self.session.delete(f"{self.resource_name}/{_id}/access_keys/", data=data, log_result=False)

@apiver.v5
class Volume(VastResource):
    resource_name = "volumes"

    @requisite(semver="5.3.0")
    def delete_by_id(self, _id, **params):
        """Delete entry by id"""
        params["params"] =  {"force": True}
        return super().delete_by_id(_id=_id, **params)

@apiver.v5
class BlockHost(VastResource):
    resource_name = "blockhosts"

    @requisite(semver="5.3.0")
    def ensure(self, node_id, transport_type, tenant_name, subsystem, **params):
        if blockhost := self.one(name=node_id, tenant_name=tenant_name):
            return blockhost
        # Need to determine the tenant_id from the subsystem
        view = self.session.views.get_subsystem(
            subsystem=subsystem,
            tenant_name=tenant_name,
        )
        data = dict(
            name=node_id,
            tenant_id=view.tenant_id,
            os_type="LINUX",
            ana="OPTIMIZED",
            connectivity_type=transport_type,
            nqn=f"{self.session.config.block_nqn_prefix}{tenant_name}:{node_id}",
        )
        return self.create(**data)


@apiver.v5
class BlockHostMapping(VastResource):
    resource_name = "blockhostvolumes"

    def map(self, volume_id, host_id):
        data = {"pairs_to_add": [{"host_id": host_id, "volume_id": volume_id}]}
        task = self.session.patch(f"{self.resource_name}/bulk", data=data)
        return self.session.wait_task(task)

    def ensure_map(self, volume_id, host_id):
        if not self.one(volume__id=volume_id, block_host__id=host_id):
            return self.map(volume_id, host_id)

    def unmap(self, volume_id, host_id):
        data = {"pairs_to_remove": [{"host_id": host_id, "volume_id": volume_id}]}
        task = self.session.patch(f"{self.resource_name}/bulk", data=data)
        return self.session.wait_task(task)

    def ensure_unmap(self, **params):
        if mapping := self.one(**params):
            return self.unmap(
                volume_id=mapping.volume["id"], host_id=mapping.block_host["id"]
            )

##########################
#
#  Test VMS Session
#
##########################
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
