import os
import json
import requests
import hashlib
import pickle
import base64
from pprint import pformat
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime
from requests.exceptions import ConnectionError
from requests.utils import default_user_agent
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

from easypy.bunch import Bunch
from easypy.caching import cached_property
from easypy.collections import shuffled
from easypy.semver import SemVer
from easypy.caching import timecache, locking_cache
from easypy.units import HOUR, MINUTE
from easypy.resilience import retrying, resilient
from easypy.humanize import yesno_to_bool
from plumbum import cmd
from plumbum import local, ProcessExecutionError

from .logging import logger
from .configuration import Config
from .exceptions import ApiError, MountFailed, OperationNotSupported, LookupFieldError
from .utils import generate_ip_range
from . import csi_types as types


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

            sw_version = self.sw_version
            if sw_version < required_version:
                if ignore:
                    return
                raise OperationNotSupported(
                    op=operation or fn.__name__,
                    required_version=required_version.dumps(),
                    current_version=self.sw_version.dumps(),
                    tip="Upgrade VAST cluster or adjust CSI driver settings to avoid unsupported operations"
                )
            return fn(self, *args, **kwargs)

        return _args_wrapper

    return dec


class CannotUseTrashAPI(OperationNotSupported):
    template = "Cannot delete folder via VMS: {reason}"


def _derive_key(salt):
    # Derive a key from the salt
    kdf = hashes.Hash(hashes.SHA256(), backend=default_backend())
    kdf.update(salt)
    return kdf.finalize()


@locking_cache
def get_vms_session(username=None, password=None, endpoint=None, ssl_cert=None):
    config = Config()
    session_cls = TestVmsSession if config.mock_vast else VmsSession
    return session_cls.create(config=config, username=username, password=password, endpoint=endpoint, ssl_cert=ssl_cert)


class RESTSession(requests.Session):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.headers["Accept"] = "application/json"
        self.headers["Content-Type"] = "application/json"
        self.headers["User-Agent"] = f"VastCSI/{config.plugin_version}.{config.ci_pipe}.{config.git_commit[:10]} ({config._mode.capitalize()}) {default_user_agent()}"
        self.headers['authorization'] = f"Bearer #"  # will be updated on first request

    @retrying.debug(times=3, acceptable=retrying.Retry)
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
            if log_result:
                for line in pformat(dict(kwargs, params=params)).splitlines():
                    logger.info(f"    {line}")
            else:
                logger.info("*** request payload is hidden ***")

        kwargs.setdefault("timeout", self.config.timeout)

        ret = super().request(
            verb, url, verify=self.ssl_verify, params=params, **kwargs
        )
        if ret.status_code == 403 and "Token is invalid or expired" in ret.text:
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

class VmsSession(RESTSession):
    """
    Communication with vms cluster.
    Operations over vip pools, quotas, snapshots etc.
    """
    def __init__(self, config, username, password, endpoint, ssl_cert):
        super().__init__(config)
        self.username = username
        self.password = password
        self.endpoint = endpoint
        self.ssl_cert = ssl_cert
        self.base_url = f"https://{endpoint}/api/v1"
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

    def serialize(self, salt: str):
        session_data = pickle.dumps((self.username, self.password, self.endpoint, self.ssl_cert))
        iv = os.urandom(16)
        key = _derive_key(salt)
        cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(session_data) + encryptor.finalize()
        # Return IV and ciphertext (both base64 encoded for storage)
        return base64.b64encode(iv + ciphertext).decode()

    @classmethod
    def deserialize(cls, salt: str, encrypted_data: str):
        encrypted_data = base64.b64decode(encrypted_data)
        # Extract IV and ciphertext
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        # Create cipher object
        key = _derive_key(salt)
        cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        # Decrypt the data
        plainbytes = decryptor.update(ciphertext) + decryptor.finalize()
        username, password, endpoint, ssl_cert = pickle.loads(plainbytes)
        return get_vms_session(username=username, password=password, endpoint=endpoint, ssl_cert=ssl_cert)

    @classmethod
    def create(cls, config, username, password, endpoint, ssl_cert):
        """
        Create instance of session.
        username, password endpoint are optional and in context of csi driver comes from secret if passed as argument.
        Otherwise, username, password and endpoint are taken from locally mounted secret (COSI case).
        """
        # The presence of the name in the arguments already indicates
        # that we have a StorageClass scope secret at this point.
        # In other words, it's not a globally mounted secret. Other secret fields will be validated below.
        is_global = not bool(username)
        if config.vms_credentials_store.exists() and is_global:
            username = config.vms_user
            password = config.vms_password
            endpoint = config.vms_host
            if not endpoint:
                raise LookupFieldError(field="endpoint", tip="Make sure endpoint is specified in values.yaml.")
        if not username:
            raise LookupFieldError(field="username", tip="Make sure username is present in secret.")
        if not password:
            raise LookupFieldError(field="password",  tip="Make sure password is present in secret.")
        if not endpoint:
            raise LookupFieldError(field="endpoint",  tip="Make sure endpoint is present in secret.")
        session = cls(config, username, password, endpoint, ssl_cert)
        config_source = "mounted configuration" if is_global else "secret"
        ssl_verification = "enabled" if session.ssl_verify else "disabled"
        logger.info(f"VMS session has been instantiated from {config_source}. SSL verification {ssl_verification}.")
        return session

    @property
    @timecache(HOUR)
    def sw_version(self) -> SemVer:
        versions = self.versions(status='success')[0].sys_version
        return SemVer.loads_fuzzy(versions)

    @requisite(semver="4.7.0")
    def delete_folder(self, path: str, tenant_id: int):
        """Delete remote cluster folder by provided path."""

        if self.config.dont_use_trash_api:
            # trash api usage is disabled by csi admin or trash api doesn't exist for cluster
            raise CannotUseTrashAPI(reason="Disabled by Vast CSI settings (see 'dontUseTrashApi' in your Helm chart)")

        try:
            self.delete("/folders/delete_folder/", data={"path": path, "tenant_id": tenant_id})
        except ApiError as e:
            if "no such directory" in e.render():
                logger.debug(f"Remote directory might have been removed earlier. ({e})")
            elif "trash folder disabled" in e.render():
                raise CannotUseTrashAPI(reason="Trash Folder Access is disabled (see Settings/Cluster/Features in VMS)")
            else:
                # unpredictable error
                raise

    def refresh_auth_token(self):
        try:
            resp = super(RESTSession, self).request(
                "POST", f"{self.base_url}/token/", verify=self.ssl_verify, timeout=5,
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
        self.usage_report()

    @requisite(semver="5.2.0", ignore=True)
    @resilient.error(msg="failed to report usage to VMS")
    def usage_report(self):
        self.post("plugins/usage/", data={
            "vendor": "vastdata", "name": "vast-csi",
            "version": self.config.plugin_version, "build": self.config.git_commit[:10]
        })

    # ----------------------------
    # View policies
    def get_view_policy(self, policy_name: str):
        """Get view policy by name. Raise exception if not found."""
        if res := self.viewpolicies(name=policy_name):
            return res[0]
        else:
            raise Exception(f"No such view policy: {policy_name}. Please create policy manually")

    # ----------------------------
    # QoS policies
    def get_qos_policy(self, policy_name: str):
        """Get QoS policy by name. Raise exception if not found."""
        if res := self.qospolicies(name=policy_name):
            return res[0]
        else:
            raise Exception(f"No such QoS policy: {policy_name}. Please create policy manually")

    # ----------------------------
    # Views
    def get_view(self, **kwargs) -> Bunch:
        """
        Get view that contain provided search kwargs eg path, bucket_name
        """
        if views := self.views(**kwargs):
            if len(views) > 1:
                raise Exception(f"Too many views were found by condition {kwargs}: {views}")
            return views[0]

    def ensure_view(self, path, protocols, view_policy, qos_policy):
        if not (view := self.get_view(path=str(path))):
            view_policy = self.get_view_policy(policy_name=view_policy)
            if qos_policy:
                qos_policy_id = self.get_qos_policy(qos_policy).id
            else:
                qos_policy_id = None
            view = self.create_view(
                path=path, protocols=protocols, policy_id=view_policy.id,
                qos_policy_id=qos_policy_id, tenant_id=view_policy.tenant_id
            )
        return view

    def ensure_s3view(self, bucket_name, root_export, **kwargs):
        if not (view := self.get_view(bucket=bucket_name)):
            view_policy = kwargs.pop("view_policy", "s3_default_policy")
            protocols = kwargs.pop("protocols", None) or []
            if protocols:
                protocols = [p.upper().strip() for p in protocols.split(",")]
            if "S3" not in protocols:
                protocols.append("S3")
            view_policy = self.get_view_policy(policy_name=view_policy)
            policy_id = view_policy.id
            tenant_id = view_policy.tenant_id
            root_export = root_export.strip("/")
            path = f"/{root_export}/{bucket_name}" if root_export else f"/{bucket_name}"
            for key in kwargs.keys():
               if kwargs[key] in ("true", "false"):
                   kwargs[key] = yesno_to_bool(kwargs[key])
            view = self.create_view(
                bucket=bucket_name, bucket_owner=bucket_name, path=path,
                protocols=protocols, policy_id=policy_id, tenant_id=tenant_id,
                **kwargs
            )
        return view

    def create_view(self, path: str, create_dir=True, **kwargs):
        """
        Create new view on remove cluster
        Args:
            path: full system path to create view for.
            **kwargs: additional view parameters.
        Returns:
            newly created view as dictionary.
        """
        data = {"path": str(path), "create_dir": create_dir, **kwargs}
        if "SMB" in kwargs.get("protocols", []):
            data["share"] = os.path.basename(path)
        return Bunch.from_dict(self.post("views", data))

    def delete_view_by_path(self, path: str):
        """Delete view by provided path criteria."""
        if view := self.get_view(path=path):
            self.delete_view_by_id(view.id)

    def delete_view_by_id(self, id_: int):
        """Delete view by provided id"""
        self.delete(f"views/{id_}")

    @contextmanager
    def temp_view(self, path, policy_id, tenant_id) -> Bunch:
        """
        Create temporary view with autogenerated alias and delite it on context manager exit.
        """
        view = self.create_view(path=path, policy_id=policy_id, tenant_id=tenant_id, alias=f"/{uuid4()}")
        try:
            yield view
        finally:
            self.delete_view_by_id(view.id)

    # ----------------------------
    @timecache(5 * MINUTE)
    def get_vip_pool(self, vip_pool_name: str) -> Bunch:
        if not (vippools := self.vippools(name=vip_pool_name)):
            raise Exception(f"No VIP Pool named '{vip_pool_name}'")
        return vippools[0]

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
        vippool = self.get_vip_pool(vip_pool_name)
        if isinstance(tenant_id, str):
            # for tenant_id passed as volume context.
            tenant_id = int(tenant_id)
        if tenant_id and vippool.tenant_id != tenant_id:
            raise Exception(
                f"Pool {vip_pool_name} belongs to tenant with id {vippool.tenant_id} but {tenant_id=} was requested"
            )
        vips = generate_ip_range(vippool.ip_ranges)
        assert vips, f"Pool {vip_pool_name} has no available vips"
        vip = shuffled(vips)[0]
        logger.info(f"Using - {vip}")
        return vip

    # ----------------------------
    # Quotas
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
    def has_snapshots(self, path):
        # we intentionally limit the number of results
        ret = self.snapshots(path__startswith=path.rstrip("/"), page_size=10)
        return ret.results

    def create_snapshot(self, name, path, tenant_id, expiration_delta=None):
        """Create new snapshot."""
        data = dict(name=name, path=path, tenant_id=tenant_id)
        if expiration_delta:
            expiration_time = (datetime.utcnow() + expiration_delta).isoformat()
            data["expiration_time"] = expiration_time
        return Bunch(self.post("snapshots", data=data))

    def get_snapshot(self, snapshot_name=None, snapshot_id=None):
        """
        Get snapshot by name or by id.
        Only one argument should be provided.
        """
        if snapshot_name:
            if ret := self.snapshots(name=snapshot_name):
                if len(ret) > 1:
                    raise Exception(f"Too many snapshots named {snapshot_name}: ({len(ret)})")
                return ret[0]
        else:
            return self.snapshots(snapshot_id)

    def ensure_snapshot(self, snapshot_name, path, tenant_id, expiration_delta=None):
        if snapshot := self.get_snapshot(snapshot_name=snapshot_name):
            if snapshot.path.strip("/") != path.strip("/"):
                raise Exception(
                    f"Snapshot already exists, but the specified path {path}"
                    f" does not correspond to the path of the snapshot {snapshot.path}"
                )
        else:
            path = path.rstrip("/") + "/"
            snapshot = self.create_snapshot(name=snapshot_name, path=path, tenant_id=tenant_id, expiration_delta=expiration_delta)
        return snapshot

    def delete_snapshot(self, snapshot_id):
        self.delete(f"snapshots/{snapshot_id}")

    def get_snapshot_stream(self, name):
        if res := self.globalsnapstreams(name=name):
            return res[0]

    def stop_snapshot_stream(self, snapshot_stream_id):
        self.patch(f"globalsnapstreams/{snapshot_stream_id}/stop")

    @requisite(semver="4.6.0", operation="create_globalsnapshotstream")
    def ensure_snapshot_stream(self, snapshot_id, tenant_id, destination_path, snapshot_stream_name):
        if not (snapshot_stream := self.get_snapshot_stream(name=snapshot_stream_name)):
            data = dict(
                loanee_root_path=destination_path,
                name=snapshot_stream_name,
                enabled=True,
                loanee_tenant_id=tenant_id, # target tenant_id
            )
            snapshot_stream = self.post(f"snapshots/{snapshot_id}/clone/", data)
        return snapshot_stream

    @requisite(semver="4.6.0", ignore=True)
    def ensure_snapshot_stream_deleted(self, snapshot_stream_name):
        """
        Stop global snapshot stream in case it is not finished.
        Snapshots with expiration time will be deleted as soon as snapshot stream is stopped.
        """
        if snapshot_stream := self.get_snapshot_stream(snapshot_stream_name):
            if snapshot_stream.status.state != "FINISHED":
                # Just stop the stream. It will be deleted automatically upon stop request.
                self.stop_snapshot_stream(snapshot_stream.id)
            else:
                self.delete(f"globalsnapstreams/{snapshot_stream.id}", data=dict(remove_dir=False))

    def get_by_token(self, token):
        """
        This method used to iterate over paginated resources (snapshots, quotas etc).
        Where after first request to resource list token for next page is returned.
        """
        return self.get(token)

    # ----------------------------
    # Users
    def create_user(self, name, uid, allow_create_bucket=False, allow_delete_bucket=False):
        return self.post("users", data={
            "name": name, "uid": uid,
            "allow_create_bucket": allow_create_bucket, "allow_delete_bucket": allow_delete_bucket
        })

    def get_user(self, name):
        if users := self.users(name=name):
            return users[0]

    def ensure_user(self, name, uid, allow_create_bucket=False, allow_delete_bucket=False):
        if user := self.get_user(name=name):
            return user
        return self.create_user(
            name=name, uid=uid, allow_create_bucket=allow_create_bucket, allow_delete_bucket=allow_delete_bucket
        )

    def delete_user(self, user_id):
        self.delete(f"users/{user_id}")

    def generate_access_key(self, user_id):
        return self.post(f"users/{user_id}/access_keys/", log_result=False)

    def delete_access_key(self, user_id, access_key):
        return self.delete(f"users/{user_id}/access_keys/", data={"access_key": access_key}, log_result=False)


class TestVmsSession(RESTSession):
    """RestSession simulation for sanity tests"""

    def __init__(self, config):
        super().__init__(config)

    @classmethod
    def create(cls, config: Config, *_, **__):
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

    @contextmanager
    def temp_view(self, path, policy_id, tenant_id):
        yield Bunch(
            id=1,
            alias=path,
            tenant_id=tenant_id,
            tenant_name="test-tenant"
        )

    def get_view(self, *_, **__):
        return Bunch(id=1, policy_id=1, tenant_id=1)

    def get_view_policy(self, *_, **__):
        return Bunch(id=1, tenant_id=1, tenant_name="test-tenant")

    def get_snapshot(self, *_, **__):
        return []

    def _empty(self, *_, **__):
        """
        empty method for test scenarios
        Method needs to be declared for compatibility with sanity tests.
        """
        pass

    update_quota = _empty
    delete_view_by_path = _empty
    delete_view_by_id = _empty
    ensure_snapshot_stream_deleted = _empty
    refresh_auth_token = _empty
    delete_folder = _empty
    is_trash_api_usable = _empty
    has_snapshots = _empty
