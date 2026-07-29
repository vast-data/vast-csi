"""
VAST API Resource classes.

This module contains all resource-specific classes for interacting
with VAST VMS API endpoints (views, quotas, snapshots, etc.).
"""

from __future__ import annotations
import os
import json
from abc import ABC
from enum import Enum
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime
from requests.exceptions import HTTPError
from typing import TYPE_CHECKING

from easypy.bunch import Bunch
from easypy.units import HOUR, MINUTE, SECOND
from easypy.resilience import resilient
from easypy.sync import wait
from easypy.collections import shuffled
from easypy.semver import SemVer
from easypy.collections import listify

from ..logging import logger
from ..exceptions import NoRecordsFound, ApiError, WaitResourceFailed
from ..utils import generate_ip_range, parse_string_parameters
from ..lru_cache import cache_on_arguments
from .base import apiver, requisite, CannotUseTrashAPI
from .iterator import ResourceIterator, DEFAULT_PAGE_SIZE

if TYPE_CHECKING:
    from .vms_session import VmsSession


class WaitCondition(str, Enum):
    """Enum for wait conditions."""
    PRESENT = "present"
    DELETED = "deleted"

class VastResource(ABC):
    resource_name = NotImplemented
    TARGET_STATE = NotImplemented
    FAILED_STATES = NotImplemented
    RUNNING_STATES = NotImplemented

    def __init__(self, session: "VmsSession"):
        self.session = session

    def iter(self, page_size=DEFAULT_PAGE_SIZE, api_ver=None, **params):
        """
        Create an iterator for paginated list results.
        
        Args:
            page_size: Number of items per page (optional)
            api_ver: API version to use (optional)
            **params: Query parameters for filtering
        
        Returns:
            ResourceIterator instance
        
        Example:
            # Get all views, automatically handling pagination
            all_views = session.views.iter(page_size=100).all()
            
            # Iterate page by page
            iterator = session.views.iter(tenant_id=1)
            for page in iterator:
                for view in page:
                    print(view.name)
        """
        return ResourceIterator(resource=self, initial_params=params, page_size=page_size, api_ver=api_ver)

    def list(self, api_ver=None, **params):
        """
        Get list of entries with optional filtering params.
        
        Automatically handles pagination by fetching all pages using the iterator.
        
        Args:
            api_ver: API version to use
            **params: Query parameters for filtering (can include page_size)
        
        Returns:
            List of all records across all pages
        
        Example:
            all_views = session.views.list(tenant_id=1)
        """
        # Use iterator to automatically handle pagination
        return self.iter(api_ver=api_ver, **params).all()

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

    def delete_many(self, api_ver=None, **params):
        """Delete multiple entries by provided params. Skip if entry not found."""
        entries = self.list(api_ver=api_ver, **params)
        for entry in entries:
            self.delete_by_id(entry.id, api_ver=api_ver)

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
                raise NoRecordsFound(f"No {resource!r} found for params {serialized_params}")
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

    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        """
        Get single entry by id.

        By default (``fail_if_missing=True``), a missing entry raises the original
        ``HTTPError`` from VMS. When ``fail_if_missing`` is False, returns None.
        """
        try:
            return self.session.get(f"{self.resource_name}/{_id}", api_ver=api_ver, **params)
        except HTTPError as exc:
            if exc.response.status_code == 404 and not fail_if_missing:
                return
            raise

    def wait(
        self,
        timeout: int = 20 * SECOND,
        sleep: int = 10 * SECOND,
        condition: WaitCondition = WaitCondition.PRESENT,
        api_ver=None,
        **params
    ):
        """
        Wait for resource presence/absence based on provided filter parameters.
        
        Args:
            timeout: Maximum time to wait in seconds (default: 1 minute)
            condition: Condition to wait for - WaitCondition.PRESENT or WaitCondition.DELETED
                      (default: WaitCondition.PRESENT)
            sleep: Time to sleep between checks in seconds (default: 10 seconds)
            api_ver: API version to use (optional)
            **params: Query parameters for filtering the resource
        
        Returns:
            The resource object when found (for PRESENT condition)
            True when resource is deleted (for DELETED condition)
        """
        resource_name = self.__class__.__name__.lower()
        serialized_params = json.dumps(params, separators=(",", ":"))
        
        # Convert string to enum if needed (for backward compatibility)
        if isinstance(condition, str):
            condition = WaitCondition(condition.lower())
        
        def wait_for_presence():
            """Check if resource exists."""
            resource = self.one(api_ver=api_ver, **params)
            if not resource:
                raise WaitResourceFailed(
                    resource=resource_name,
                    condition=condition.value
                )
            return resource
        
        def wait_for_absence():
            """Check if a resource does not exist."""
            resource = self.one(api_ver=api_ver, **params)
            if resource:
                raise WaitResourceFailed(
                    resource=resource_name,
                    condition=condition.value
                )
            return True
        
        error_msg = f"Waiting for {resource_name} with params {serialized_params} to be {condition.value}"

        if condition == WaitCondition.DELETED:
            return wait(timeout, wait_for_absence, sleep=sleep, message=error_msg)
        else:
            return wait(timeout, wait_for_presence, sleep=sleep, message=error_msg)


    def _wait_for_state(self, resource_id, timeout=None, keys=("state",), log_result = True, sleep = 5):
        """
        Wait for a resource to reach a specific state.
        
        Args:
            resource_id: The resource ID to wait for
        """

        def is_resource_in_target_state():
            state = None
            resource = self.get(resource_id, log_result=log_result)
            for key in keys:
               state = getattr(resource, key, None) if hasattr(resource, key) else resource.get(key)
               if state:
                   break

            # Normalize state to lowercase for comparison
            if state:
                state = state.lower()

            # Normalize TARGET_STATE to a list of lowercase strings.
            target_states = [t.lower() for t in listify(self.TARGET_STATE)]

            failed_states = [s.lower() if isinstance(s, str) else s for s in self.FAILED_STATES]
            running_states = [s.lower() if isinstance(s, str) else s for s in self.RUNNING_STATES]

            if state in target_states:
                logger.info(f"{self.resource_name} {resource_id} reached target state: {state}")
                return True
            elif state in failed_states:
                raise Exception(f"{self.resource_name} {resource_id} failed with state: {state}")
            elif state in running_states:
                logger.info(f"{self.resource_name} {resource_id} still running (state: {state})")
                return False
            else:
                raise Exception(
                    f"Unknown {self.resource_name} state: {state}. "
                    f"Expected one of: TARGET={target_states}, "
                    f"RUNNING={running_states}, FAILED={failed_states}"
                )

        if timeout is None:
            timeout = self.session.config.timeout
        logger.info(f"Waiting for {self.resource_name} {resource_id} to reach state '{self.TARGET_STATE}' (timeout: {timeout}s)...")

        wait(
            timeout,
            is_resource_in_target_state,
            sleep=sleep,
            message=f"{self.resource_name} "
                    f"{resource_id} did not reach state '{self.TARGET_STATE}' within {timeout} seconds",
        )


class Version(VastResource):
    resource_name = "versions"

    @cache_on_arguments(expiration_time=HOUR)
    def get_sw_version(self) -> SemVer:
        """Get VMS software version."""
        versions = self.list(status="success")[0].sys_version
        return SemVer.loads_fuzzy(versions)

class Plugin(VastResource):
    resource_name = "plugins"

    @resilient.error(msg="failed to report usage to VMS")
    @cache_on_arguments(expiration_time=20 * MINUTE)
    def usage_report(self):
        """
        Sends plugin usage statistics to VMS.
        
        Called opportunistically after successful requests.
        Rate-limited to once every 20 minutes via caching.
        Thread-safe: dogpile.cache handles locking internally.
        """
        self.session.post(f"{self.resource_name}/usage/",
            data={
                "vendor": "vastdata",
                "name": "vast-csi",
                "version": self.session.config.plugin_version,
                "build": self.session.config.git_commit[:10]
            })

class ViewPolicy(VastResource):
    resource_name = "viewpolicies"

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        return super().get(_id, fail_if_missing=fail_if_missing, api_ver=api_ver, **params)


class QosPolicy(VastResource):
    resource_name = "qospolicies"

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        return super().get(_id, fail_if_missing=fail_if_missing, api_ver=api_ver, **params)


class Tenant(VastResource):
    resource_name = "tenants"

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        return super().get(_id, fail_if_missing=fail_if_missing, api_ver=api_ver, **params)


class S3LifecycleRule(VastResource):
    resource_name = "s3lifecyclerules"

    def ensure(self, name, view_id, **params):
        entry = self.one(name=name, view__id=view_id)
        if not entry:
            entry = self.create(name=name, view_id=view_id, **params)
        return entry


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
            # Parse string parameters to proper types
            kwargs = parse_string_parameters(kwargs)

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
    @apiver.v5
    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get_subsystem(self, subsystem, **params):
        """Get BLOCK type view by provided name."""
        view = self.one(name=subsystem, fail_if_missing=True, **params)
        assert "BLOCK" in view.protocols, f"View {view.name} is not a block volume"
        return view

    @requisite(semver="5.3.0")
    @apiver.v5
    @cache_on_arguments(expiration_time=5 * MINUTE)
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

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        return super().get(_id, fail_if_missing=fail_if_missing, api_ver=api_ver, **params)

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
            kwargs.update(path__endswith=name)
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
        return ret

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
        return any(s.status.get("state", "").lower() != "finished" for s in resp)

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

    def generate_access_key(self, _id, *, access_key=None, secret_key=None, tenant_id=None):
        data = {}
        if tenant_id is not None:
            data["tenant_id"] = tenant_id
        if (access_key is None) ^ (secret_key is None):
            raise ValueError("access_key and secret_key must both be set or both omitted")
        if access_key is not None and secret_key is not None:
            data["access_key"] = access_key
            data["secret_key"] = secret_key
        return self.session.post(
            f"{self.resource_name}/{_id}/access_keys/", data=data, log_result=False
        )

    def list_access_keys(self, user_id):
        """Return access-key ID strings from GET /users/{id} (session default api v1).

        Assumes each ``user.access_keys`` entry is a sequence whose first
        element is the access-key string (Orion api v1 representation).
        """
        user = self.get(user_id)
        return [item[0] for item in user.access_keys or []]

    def delete_access_key(self, _id, access_key):
        data = dict(access_key=access_key)
        return self.session.delete(f"{self.resource_name}/{_id}/access_keys/", data=data, log_result=False)

@apiver.v5
class Volume(VastResource):
    resource_name = "volumes"

    @requisite(semver="5.3.0")
    def delete_by_id(self, _id, **params):
        """Delete entry by id. Retries with force=True if volume is still mapped to hosts."""
        try:
            return super().delete_by_id(_id=_id, **params)
        except ApiError as exc:
            if exc.response.status_code == 400 and "Volume is mapped to hosts" in exc.response.text:
                logger.warning(f"Volume {_id} is mapped to hosts, retrying delete with force=True.")
                return super().delete_by_id(_id=_id, params={"force": True}, **params)
            raise

@apiver.v5
class BlockHost(VastResource):
    resource_name = "blockhosts"

    @requisite(semver="5.3.0")
    def ensure(self, node_id, transport_type, tenant_name, subsystem, nqn, **params):
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
            nqn=nqn,
        )
        try:
            return self.create(**data)
        except ApiError as exc:
            text = exc.response.text
            is_duplicate = (
                exc.response.status_code == 400
                and (
                    "unique set" in text
                    or "unique_block_host_name_per_tenant" in text
                )
            )
            if is_duplicate and (blockhost := self.one(name=node_id, tenant_name=tenant_name)):
                logger.info(
                    "Block host %r (tenant=%r) already exists; using existing entry",
                    node_id,
                    tenant_name,
                )
                return blockhost
            raise


@apiver.v5
class BlockHostMapping(VastResource):
    resource_name = "blockhostvolumes"

    def map(self, volume_id, host_id):
        data = {"pairs_to_add": [{"host_id": host_id, "volume_id": volume_id}]}
        task = self.session.patch(f"{self.resource_name}/bulk", data=data)
        return self.session.wait_task(task, retry_key=str(volume_id))

    def ensure_map(self, volume_id, host_id):
        if not self.one(volume__id=volume_id, block_host__id=host_id):
            return self.map(volume_id, host_id)

    def ensure_map_exclusive(self, volume_id, host_id):
        """Ensure volume is mapped to exactly one host (host_id) for single-node access modes.

        Unlike ensure_map, this method queries all existing mappings for the
        volume (not filtered by host) and enforces that only the requested host
        has a mapping.
        """
        existing = self.list(volume__id=volume_id)

        stale = [m for m in existing if m.block_host["id"] != host_id]
        if stale:
            host_names = [m.block_host.get("name", m.block_host["id"]) for m in stale]
            raise Exception(
                f"Volume {volume_id} is already mapped to {host_names} — "
                f"unexpected for single-node access mode (expected host {host_id} only)"
            )
        if not any(m.block_host["id"] == host_id for m in existing):
            return self.map(volume_id, host_id)

    def unmap(self, volume_id, host_id):
        data = {"pairs_to_remove": [{"host_id": host_id, "volume_id": volume_id}]}
        task = self.session.patch(f"{self.resource_name}/bulk", data=data)
        return self.session.wait_task(task, retry_key=str(volume_id))

    def ensure_unmap(self, **params):
        if mapping := self.one(**params):
            return self.unmap(
                volume_id=mapping.volume["id"],
                host_id=mapping.block_host["id"],
            )

@apiver.v5
class ProtectionPolicy(VastResource):
    resource_name = "protectionpolicies"

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def one(self, **params):
        return super().one(**params)

    @cache_on_arguments(expiration_time=5 * MINUTE)
    def get(self, _id, fail_if_missing=True, api_ver=None, **params):
        return super().get(_id, fail_if_missing=fail_if_missing, api_ver=api_ver, **params)

@apiver.v5
class ProtectedPath(VastResource):
    resource_name = "protectedpaths"
    # "Partially Active" is the normal steady state for group-replication ppaths
    # (multiple destination members).  It is a valid terminal state, not a
    # transient one, so it belongs in TARGET_STATE alongside "active".
    TARGET_STATE = "active"
    FAILED_STATES = ["delete_pending", "error", "failed", "suspended"]
    RUNNING_STATES = [
        "n/a",
        "initializing",
        "initial scan",
        "syncing",
        "joining",
        "initial sync",
        "partially active",
        "replication ready",
        "waiting for a standby stream",
        "waiting for a remote peer setup",
        "waiting for sync point to member",
    ]

    def wait_active(self, resource_id):
        """Wait for protected path to reach target state.

        Override to check both 'state' (operational state) and 'protected_path_state' (sync state)
        by default, since protected paths have dual state tracking.

        Args:
            resource_id: Protected path ID
        """
        return super()._wait_for_state(
            resource_id,
            timeout=None,
            keys=("state", "protected_path_state"),
            log_result=False,
            sleep=15,
        )

    def set_enabled(self, protected_path_id, enabled: bool):
        """Set protected path enabled state.

        Args:
            protected_path_id: ID of the protected path
            enabled: True to enable, False to disable
        """
        return self.update(protected_path_id, enabled=enabled)

    def ensure_set_enabled(self, ppath: Bunch, enabled: bool) -> bool:
        """Ensure a protected path is enabled or disabled."""
        if ppath.enabled != enabled:
            self.set_enabled(ppath.id, enabled=enabled)
            return True
        return False

    def replicate_now(self, protected_path_id, time_expires_local: str, time_expires_target: str):
        """Trigger replication on all streams of the protected path immediately.

        Args:
            protected_path_id: ID of the protected path
            time_expires_local: Expiration time for local snapshot (timestamp format: YYYY-mm-ddTHH:MM:SS)
            time_expires_target: Expiration time for target snapshot (timestamp format: YYYY-mm-ddTHH:MM:SS)

        Note:
            Use parse_duration_to_timestamp() from utils to convert protection policy
            duration strings (like "2H", "30m") to the required timestamp format.
        """
        data = {
            "time_expires_local": time_expires_local,
            "time_expires_target": time_expires_target,
        }
        return self.session.patch(f"{self.resource_name}/{protected_path_id}/replicate_now/", data=data)

    def ensure_replicate_now(self, name: str, time_expires_local: str, time_expires_target: str):
        """Find protected path by name and trigger replication immediately.

        Args:
            name: Name of the protected path
            time_expires_local: Expiration time for local snapshot (timestamp format: YYYY-mm-ddTHH:MM:SS)
            time_expires_target: Expiration time for target snapshot (timestamp format: YYYY-mm-ddTHH:MM:SS)
        """
        protected_path = self.one(name=name, fail_if_missing=True)
        return self.replicate_now(protected_path.id, time_expires_local, time_expires_target)

    def failover(self, protected_path_id, graceful: bool):
        """Initiate a failover of a protected path, transitioning it toward SOURCE role.

        - ``graceful=True``: coordinates with the remote SOURCE cluster to drain
          in-flight I/O before switching roles.  Both sides transition cleanly —
          the remote becomes ``DESTINATION`` and the local becomes ``SOURCE``.

        - ``graceful=False``: severs the replication link immediately without
          waiting for the remote.  Both sides land on ``STANDALONE`` — neither is
          SOURCE yet.  A subsequent :meth:`force_failover` call is required to
          promote the local ``STANDALONE`` to ``SOURCE``.

        Args:
            protected_path_id: ID of the protected path.
            graceful: ``True`` for a graceful failover, ``False`` for ungraceful.
        """
        return self.update(protected_path_id, failover=True, graceful=graceful)

    def force_failover(self, protected_path_id, wait_failover: bool = True):
        """Promote a STANDALONE protected path to SOURCE without contacting the remote cluster.

        This is the second step of an ungraceful failover sequence.  After
        :meth:`failover(graceful=False)` leaves both sides in ``STANDALONE``,
        ``force_failover`` unilaterally declares the local side the new primary.
        It does not require the original SOURCE to be reachable, making it
        suitable for disaster-recovery scenarios where the remote cluster is
        offline or unreachable.

        Unlike :meth:`failover`, this call is fire-and-forget toward the remote —
        the original SOURCE will detect the detachment via an ``ALERT`` when it
        comes back online.

        Args:
            protected_path_id: ID of the protected path (must be in ``STANDALONE`` role).
            wait_failover: If ``True``, block until the async VMS task completes
                and the role has transitioned to ``SOURCE``.

        Returns:
            API response containing the async task handle.
        """
        logger.info(f"Performing force failover on protected path {protected_path_id}")
        response = self.session.patch(f"{self.resource_name}/{protected_path_id}/force_failover/")

        if wait_failover:
            # Wait for the async task to complete
            self.session.wait_task(response, sleep=20)
            logger.info(f"Force failover task completed for protected path {protected_path_id}")
        return response

    def delete_by_id(self, _id, api_ver=None, **params):
        task = super().delete_by_id(_id=_id, api_ver=api_ver, **params)
        return self.session.wait_task(task)


@apiver.v5
class ReplicationPeers(VastResource):
    resource_name = "nativereplicationremotetargets"

class Cluster(VastResource):
    resource_name = "clusters"

    @cache_on_arguments(expiration_time=HOUR)
    def one(self, **params):
        return self.list(**params)[0]
