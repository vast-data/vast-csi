from dataclasses import dataclass
from abc import ABC
from datetime import timedelta
from typing import Optional, final, TypeVar

from . import csi_types as types
from .utils import is_ver_nfs4_present
from plumbum import local

from .exceptions import VolumeAlreadyExists, SourceNotFound

CreatedVolumeT = TypeVar("CreatedVolumeT")


class VolumeBuilderI(ABC):
    """Base Volume Builder interface"""

    def build_volume_name(self, **kwargs) -> str:
        """
        Final implementation should build volume name from provided argumenents and/or from other params
        depends on conditions.
        """
        ...

    def get_requested_capacity(self) -> int:
        """Final implementation should return requested capacity based on provided params and/or other inputs"""
        ...

    def get_existing_capacity(self) -> int:
        """Final implementation should return existing voume capacity based on provided params and/or other inputs"""
        ...

    def build_volume(self, **kwargs) -> CreatedVolumeT:
        """
        Final implementation shoud perform final actions for creationg volume and/or return all necessary
        data to create volume.
        """
        ...


# ----------------------------------------------------------------------------------------------------------------------
# Final builders
# ----------------------------------------------------------------------------------------------------------------------
@dataclass
class BaseBuilder(VolumeBuilderI):
    """Common builder with shared methods/attributes"""

    controller: "ControllerServicer"
    configuration: "CONF"

    name: str  # Name of volume or snapshot
    rw_access_mode: bool
    root_export: str
    volume_name_fmt: str
    view_policy: str
    vip_pool_name: str
    mount_options: str
    lb_strategy: str
    qos_policy: Optional[str]

    capacity_range: Optional[int]  # Optional desired volume capacity
    pvc_name: Optional[str]
    pvc_namespace: Optional[str]
    volume_content_source: Optional[str]  # Either volume or snapshot
    ephemeral_volume_name: Optional[str] = None

    def get_requested_capacity(self) -> int:
        """Return desired allocated capacity if provided else return 0"""
        return self.capacity_range.required_bytes if self.capacity_range else 0


class EmptyVolumeBuilder(BaseBuilder):
    """Builder for k8s PersistentVolumeClaim, PersistentVolume etc."""

    def build_volume_name(self) -> str:
        """Build volume name using format csi:{namespace}:{name}:{id}"""
        volume_id = self.name
        if self.ephemeral_volume_name:
            volume_name = self.ephemeral_volume_name
        elif self.pvc_name and self.pvc_namespace:
            volume_name = self.volume_name_fmt.format(
                namespace=self.pvc_namespace, name=self.pvc_name, id=volume_id
            )
        else:
            volume_name = f"csi-{volume_id}"

        if self.configuration.truncate_volume_name:
            volume_name = volume_name[:self.configuration.truncate_volume_name]  # crop to Vast's max-length

        return volume_name

    @property
    def mount_protocol(self):
        return "NFS4" if is_ver_nfs4_present(self.mount_options) else "NFS"

    @property
    def volume_context(self):
        return {
            "root_export": self.root_export,
            "vip_pool_name": self.vip_pool_name,
            "lb_strategy": self.lb_strategy,
            "mount_options": self.mount_options,
            "view_policy": self.view_policy,
            "protocol": self.mount_protocol,
        }

    @property
    def view_path(self):
        return str(local.path(self.root_export)[self.name])

    def build_volume(self) -> types.Volume:
        """
        Main build entrypoint for volumes.
        Create volume from pvc, pv etc.
        """
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        # Check if view with expected system path already exists.
        view = self.controller.vms_session.ensure_view(
            path=self.view_path, protocol=self.mount_protocol, view_policy=self.view_policy, qos_policy=self.qos_policy
        )
        quota = self._ensure_quota(requested_capacity, volume_name, self.view_path, view.tenant_id)
        volume_context.update(quota_id=str(quota.id), view_id=str(view.id), tenant_id=str(view.tenant_id))

        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
            volume_context=volume_context,
        )

    def _ensure_quota(self, requested_capacity, volume_name, view_path, tenant_id):
        if quota := self.controller.vms_session.get_quota(self.name):
            # Check if volume with provided name but another capacity already exists.
            if quota.hard_limit != requested_capacity:
                raise VolumeAlreadyExists(
                    "Volume already exists with different capacity than requested "
                    f"({quota.hard_limit})")
            if quota.tenant_id != tenant_id:
                raise VolumeAlreadyExists(
                    "Volume already exists with different tenancy ownership "
                    f"({quota.tenant_name})")

        else:
            data = dict(
                name=volume_name,
                path=view_path,
                tenant_id=tenant_id
            )
            if requested_capacity:
                data.update(hard_limit=requested_capacity)
            quota = self.controller.vms_session.create_quota(data=data)
        return quota


@final
class VolumeFromVolumeBuilder(EmptyVolumeBuilder):
    """Cloning volumes from existing."""

    def build_volume(self) -> types.Volume:
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        source_volume_id = self.volume_content_source.volume.volume_id
        if not (source_quota := self.controller.vms_session.get_quota(source_volume_id)):
            raise SourceNotFound(f"Unknown volume: {source_volume_id}")

        source_path = source_quota.path
        tenant_id = source_quota.tenant_id
        snapshot_name = f"snp-{self.name}"
        snapshot_stream_name = f"strm-{self.name}"

        snapshot = self.controller.vms_session.ensure_snapshot(
            snapshot_name=snapshot_name, path=source_path,
            tenant_id=tenant_id, expiration_delta=timedelta(minutes=5)
        )
        snapshot_stream = self.controller.vms_session.ensure_snapshot_stream(
            snapshot_id=snapshot.id, destination_path=self.view_path, tenant_id=tenant_id,
            snapshot_stream_name=snapshot_stream_name,
        )
        # View should go after snapshot stream.
        # Otherwise snapshot stream action will detect folder already exist and will be rejected
        view = self.controller.vms_session.ensure_view(
            path=self.view_path, protocol=self.mount_protocol,
            view_policy=self.view_policy, qos_policy=self.qos_policy
        )
        quota = self._ensure_quota(requested_capacity, volume_name, self.view_path, view.tenant_id)
        volume_context.update(
            quota_id=str(quota.id), view_id=str(view.id),
            tenant_id=str(tenant_id), snapshot_stream_name=snapshot_stream.name
        )

        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
            content_source=types.VolumeContentSource(
                volume=types.VolumeSource(volume_id=source_volume_id)
            ),
            volume_context=volume_context,
        )


@final
class VolumeFromSnapshotBuilder(EmptyVolumeBuilder):
    """Builder for k8s Snapshots."""

    def build_volume(self) -> types.Volume:
        """
        Main entry point for snapshots.
        Create snapshot representation.
        """
        source_snapshot_id = self.volume_content_source.snapshot.snapshot_id
        if not (snapshot := self.controller.vms_session.get_snapshot(snapshot_id=source_snapshot_id)):
            raise SourceNotFound(f"Unknown snapshot: {source_snapshot_id}")
        volume_context = self.volume_context

        if self.rw_access_mode:
            # Create volume from snapshot for READ_WRITE modes.
            #   quota and view will be created.
            #   The contents of the source snapshot will be replicated to view folder
            #   using an intermediate global snapshot stream.
            tenant_id = snapshot.tenant_id
            volume_name = self.build_volume_name()
            requested_capacity = self.get_requested_capacity()
            volume_context["volume_name"] = volume_name

            snapshot_stream_name = f"strm-{self.name}"
            snapshot_stream = self.controller.vms_session.ensure_snapshot_stream(
                snapshot_id=snapshot.id, destination_path=self.view_path, tenant_id=tenant_id,
                snapshot_stream_name=snapshot_stream_name,
            )
            view = self.controller.vms_session.ensure_view(
                path=self.view_path, protocol=self.mount_protocol,
                view_policy=self.view_policy, qos_policy=self.qos_policy
            )
            quota = self._ensure_quota(requested_capacity, volume_name, self.view_path, tenant_id)
            volume_context.update(
                quota_id=str(quota.id), view_id=str(view.id),
                tenant_id=str(tenant_id), snapshot_stream_name=snapshot_stream.name
            )

        else:
            # Create volume from snapshot for READ_ONLY modes.
            #   Such volume has no quota and view representation on VAST.
            #   Volume within pod will be directly mounted to snapshot source folder.
            requested_capacity = 0  # read-only volumes from snapshots have no capacity.
            snapshot_path = local.path(snapshot.path)
            # Compute root_export from snapshot path. This value should be passed as context for appropriate
            # mounting within 'ControllerPublishVolume' endpoint
            self.root_export = snapshot_path.parent
            path = snapshot_path / ".snapshot" / snapshot.name
            snapshot_base_path = str(path.relative_to(self.root_export))
            volume_context.update(snapshot_base_path=snapshot_base_path, root_export=self.root_export)

        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
            content_source=types.VolumeContentSource(
                snapshot=types.SnapshotSource(snapshot_id=source_snapshot_id)
            ),
            volume_context=volume_context
        )


@final
class TestVolumeBuilder(BaseBuilder):
    """Test volumes builder for sanity checks"""

    def build_volume_name(self) -> str:
        pass

    def get_existing_capacity(self) -> Optional[int]:
        volume = self.controller.vms_session.get_quota(self.name)
        if volume:
            return volume.capacity_bytes

    def build_volume(self) -> types.Volume:
        """Main build entrypoint for tests"""
        if content_source := self.volume_content_source:
            if content_source.snapshot.snapshot_id:
                if not self.configuration.fake_snapshot_store[content_source.snapshot.snapshot_id].exists():
                    raise SourceNotFound(f"Source snapshot does not exist: {content_source.snapshot.snapshot_id}")
            elif content_source.volume.volume_id:
                if not self.configuration.fake_quota_store[content_source.volume.volume_id].exists():
                    raise SourceNotFound(f"Source volume does not exist: {content_source.volume.volume_id}")

        requested_capacity = self.get_requested_capacity()
        if existing_capacity := self.get_existing_capacity():
            if existing_capacity != requested_capacity:
                raise VolumeAlreadyExists(
                    "Volume already exists with different capacity than requested"
                    f"({existing_capacity})",
                )

        vol_dir = self.controller.vms_session._mock_mount[self.name]
        vol_dir.mkdir()

        volume = types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
        )

        with self.configuration.fake_quota_store[self.name].open("wb") as f:
            f.write(volume.SerializeToString())
        return volume
