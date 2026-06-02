"""
VMS Session implementation for VAST CSI.

This module contains the main VmsSession class that manages
communication with VAST VMS API clusters.
"""

import hashlib
import threading
from requests.exceptions import ConnectionError

from easypy.bunch import Bunch

from ..logging import logger
from ..exceptions import ApiError, LookupFieldError
from ..serialization_utils import SerializationMixin
from .base import RESTSession, get_vms_session
from .wait import wait_task as _wait_task

# Import resources to register them
from .resources import (
    Version, Plugin, ViewPolicy, View, QosPolicy, Tenant,
    Folder, VipPool, Quota, Snapshot, GlobalSnapshotStream,
    User, Volume, BlockHost, BlockHostMapping,
    ProtectionPolicy, ProtectedPath, Cluster
)


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

        # Thread-safe locks for shared operations across gRPC workers
        self._token_refresh_lock = threading.RLock()
        self._token_refresh_cond = threading.Condition(self._token_refresh_lock)
        self._authorizing = False

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
        if config.max_cache_control_seconds:
            self.headers["Cache-Control"] = f"max-age={config.max_cache_control_seconds}"

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
        self.protectionpolicies = ProtectionPolicy(self)
        self.protectedpaths = ProtectedPath(self)
        self.clusters = Cluster(self)

    def __str__(self):
        return f"{self.__class__.__name__}[{self.endpoint}]"

    __repr__ = __str__

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
        logger.info(f"{session} has been instantiated from {config_source}{tenant_scope}. SSL verification {ssl_verification}.")
        return session

    def refresh_auth_token(self):
        """
        Refreshes the authentication token.

        This method implements a thread-safe, single-authorization-at-a-time pattern
        to prevent the "thundering herd" problem where multiple gRPC workers would all
        attempt to refresh tokens simultaneously, causing redundant API calls.

        Concurrency Strategy:

        1. Authorization In Progress Flag (self._authorizing):
           - Acts as a signal that one worker is currently refreshing the token
           - Protected by self._token_refresh_lock for thread-safe access

        2. Condition Variable (self._token_refresh_cond):
           - Coordinates workers waiting for token refresh to complete
           - wait() atomically: releases lock → sleeps → re-acquires lock when signaled
           - notify_all() wakes all waiting workers when refresh completes

        3. Token Clearing Strategy:
           - Before attempting refresh, we clear the authorization header
           - This ensures waiting workers won't use stale/invalid tokens if refresh fails
           - If refresh succeeds, the new token is written; if it fails, header stays empty

        Flow for Concurrent Calls:

        Worker 1 (first to arrive):
          → Acquires lock
          → Sets self._authorizing = True
          → Clears authorization header (invalidate old token)
          → Releases lock
          → Makes HTTP call to refresh token
          → Sets self._authorizing = False, notify_all() to wake waiters

        Workers 2-N (arrive while Worker 1 is working):
          → Acquire lock
          → See self._authorizing = True
          → Call self._token_refresh_cond.wait() - releases lock and sleeps
          → Woken by notify_all() when Worker 1 completes
          → Re-acquire lock and check if token is now available:
             - If token exists → return (use Worker 1's token)
             - If token is empty → Worker 2 tries refresh (Worker 1 failed)

        This design ensures:
          - Only 1 HTTP call per refresh attempt (no thundering herd)
          - Automatic retry on transient failures (next waiting worker tries)
          - Thread-safe access to shared self.headers state
        """
        with self._token_refresh_lock:
            # Wait while another worker is authorizing
            if self._authorizing:
                logger.info("Token refresh already in progress by another worker, waiting...")
                while self._authorizing:
                    self._token_refresh_cond.wait()  # Releases lock and waits, re-acquires when signaled

                # We were waiting - check if token is now available
                if self.headers.get("authorization"):
                    logger.info("Token refresh completed by another worker, using existing token")
                    return

            # We're the first - set authorizing flag
            self._authorizing = True
            logger.info("Starting token refresh request to VMS")

            # Clear the authorization header before attempting refresh
            # This ensures waiting workers won't use stale token if refresh fails
            self.headers["authorization"] = ""

        # Now make HTTP call without holding the lock
        try:
            resp = super(RESTSession, self).request(
                "POST", f"{self.base_url}/v1/token/", verify=self.ssl_verify, timeout=30,
                json={"username": self.username, "password": self.password}
            )
            resp.raise_for_status()
            token = resp.json()["access"]

            with self._token_refresh_lock:
                self.headers["authorization"] = f"Bearer {token}"
                logger.info("Successfully refreshed auth token from VMS")
        except ConnectionError as e:
            raise ApiError(
                response=Bunch(
                    status_code=None,
                    text=f"The vms on the designated host {self.config.vms_host!r} "
                         f"cannot be accessed. Please verify the specified endpoint. "
                         f"origin error: {e}"
                ))
        finally:
            # Clear authorizing flag and notify waiting workers
            with self._token_refresh_lock:
                self._authorizing = False
                self._token_refresh_cond.notify_all()  # Wake up all waiting workers

    def wait_task(
        self, task, latest=False, start_timeout=0, verbose=True, sleep=None, retry_key=None,
    ):
        return _wait_task(
            self, task,
            latest=latest,
            start_timeout=start_timeout,
            verbose=verbose,
            sleep=sleep,
            retry_key=retry_key,
        )
