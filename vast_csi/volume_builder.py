import os
import re
from dataclasses import dataclass
from abc import ABC
from base64 import b32encode
from random import getrandbits
from datetime import timedelta
from typing import Optional, final, TypeVar

from easypy.bunch import Bunch

from . import csi_types as types
from .csi_types import INVALID_ARGUMENT
from .utils import is_ver_nfs4_present
from plumbum import local

from .exceptions import VolumeAlreadyExists, SourceNotFound, Abort, MissingParameter
from .utils import is_valid_ip
from .quantity import parse_quantity

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

    @classmethod
    def from_parameters(cls, *args, **kwargs):
        """Parse context and return builder instance."""
        ...


@dataclass
class BaseBuilder(VolumeBuilderI):
    """Common builder with shared methods/attributes"""

    # Required
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str  # Name of volume or snapshot
    rw_access_mode: bool
    root_export: str
    volume_name_fmt: str
    view_policy: str
    mount_options: str

    # Optional
    volume_content_source: Optional[str] = None  # Either volume or snapshot
    ephemeral_volume_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    qos_policy: Optional[str] = None
    capacity_range: Optional[int] = None # Optional desired volume capacity
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None

    @property
    def mount_protocol(self) -> str:
        return "NFS4" if is_ver_nfs4_present(self.mount_options) else "NFS"

    @property
    def volume_context(self) -> dict:
        context = {
            "root_export": self.root_export_abs,
            "mount_options": self.mount_options,
            "view_policy": self.view_policy,
            "protocol": self.mount_protocol,
        }
        if self.vip_pool_name:
            context["vip_pool_name"] = self.vip_pool_name
        elif self.vip_pool_fqdn:
            context["vip_pool_fqdn"] = self.vip_pool_fqdn_with_prefix
        return context

    @property
    def view_path(self) -> str:
        return os.path.join(self.root_export_abs, self.name)

    @property
    def root_export_abs(self) -> str:
        return os.path.join("/", self.root_export)

    @property
    def vip_pool_fqdn_with_prefix(self) -> str:
        prefix = b32encode(getrandbits(16).to_bytes(2, "big")).decode("ascii").rstrip("=")
        return f"{prefix}.{self.vip_pool_fqdn}"


    @classmethod
    def from_parameters(
            cls,
            conf,
            vms_session,
            name,
            volume_capabilities,
            capacity_range,
            parameters,
            volume_content_source,
            ephemeral_volume_name,
    ) -> "BaseBuilder":
        """Parse context and return builder instance."""
        mount_options = cls._parse_mount_options(volume_capabilities)
        rw_access_mode = cls._parse_access_mode(volume_capabilities)
        root_export = cls._get_required_param(parameters, "root_export")
        view_policy = cls._get_required_param(parameters, "view_policy")

        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)

        volume_name_fmt = parameters.get("volume_name_fmt", conf.name_fmt)
        qos_policy = parameters.get("qos_policy")

        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            rw_access_mode=rw_access_mode,
            capacity_range=capacity_range,
            pvc_name=parameters.get("csi.storage.k8s.io/pvc/name"),
            pvc_namespace=parameters.get("csi.storage.k8s.io/pvc/namespace"),
            volume_content_source=volume_content_source,
            ephemeral_volume_name=ephemeral_volume_name,
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            mount_options=mount_options,
            qos_policy=qos_policy,
        )

    @classmethod
    def _get_required_param(cls, parameters, param_name):
        """Get required parameter or raise MissingParameter exception."""
        value = parameters.get(param_name)
        if value is None:
            raise MissingParameter(param=param_name)
        return value

    @classmethod
    def _parse_mount_options(cls, volume_capabilities):
        """Get mount options from volume capabilities."""
        try:
            mount_capability = next(cap for cap in volume_capabilities if cap.HasField("mount"))
            mount_flags = mount_capability.mount.mount_flags
            mount_options = ",".join(mount_flags)
            return ",".join(re.sub(r"[\[\]]", "", mount_options).replace(",", " ").split())
        except StopIteration:
            return ""

    @classmethod
    def _parse_access_mode(cls, volume_capabilities):
        """Check if list of provided access modes contains read-write mode."""
        rw_access_modes = {
            types.AccessModeType.SINGLE_NODE_WRITER,
            types.AccessModeType.MULTI_NODE_MULTI_WRITER
        }
        return any(
            cap.access_mode.mode in rw_access_modes
            for cap in volume_capabilities if cap.HasField("access_mode")
        )

    @classmethod
    def _validate_mount_src(cls, vip_pool_name, vip_pool_fqdn, local_ip_for_mount):
        """Validate that only one of vip_pool_name, vip_pool_fqdn or local_ip_for_mount is provided."""
        if vip_pool_name and vip_pool_fqdn:
            raise Abort(
                INVALID_ARGUMENT,
                "vip_pool_name and vip_pool_fqdn are mutually exclusive. Provide one of them."
            )
        if not (vip_pool_name or vip_pool_fqdn) and not local_ip_for_mount:
            raise Abort(
                INVALID_ARGUMENT,
                "either vip_pool_name, vip_pool_fqdn or use_local_ip_for_mount must be provided."
            )
        if local_ip_for_mount and not is_valid_ip(local_ip_for_mount):
            raise Abort(INVALID_ARGUMENT, f"Local IP address: {local_ip_for_mount} is invalid")

    def get_requested_capacity(self) -> int:
        """Return desired allocated capacity if provided, else return 0."""
        return self.capacity_range.required_bytes if self.capacity_range else 0

    def build_volume_name(self) -> str:
        """Build volume name using format csi:{namespace}:{name}:{id}"""
        volume_id = self.name
        if self.ephemeral_volume_name:
            return self.ephemeral_volume_name

        if self.pvc_name and self.pvc_namespace:
            volume_name = self.volume_name_fmt.format(
                namespace=self.pvc_namespace, name=self.pvc_name, id=volume_id
            )
        else:
            volume_name = f"csi-{volume_id}"

        if self.configuration.truncate_volume_name:
            volume_name = volume_name[:self.configuration.truncate_volume_name]

        return volume_name


# ----------------------------------------------------------------------------------------------------------------------
# Final builders
# ----------------------------------------------------------------------------------------------------------------------

@final
class EmptyVolumeBuilder(BaseBuilder):
    """Builder for k8s PersistentVolumeClaim, PersistentVolume etc."""

    def build_volume(self) -> types.Volume:
        """Main build entrypoint for volumes."""
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        view = self.vms_session.ensure_view(
            path=self.view_path, protocols=[self.mount_protocol], view_policy=self.view_policy,
            qos_policy=self.qos_policy
        )
        quota = self.vms_session.ensure_quota(
            volume_id=volume_name, view_path=self.view_path,
            tenant_id=view.tenant_id, requested_capacity=requested_capacity
        )
        volume_context.update(
            quota_id=str(quota.id),
            view_id=str(view.id),
            tenant_id=str(view.tenant_id)
        )

        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
            volume_context=volume_context,
        )


@final
class VolumeFromVolumeBuilder(BaseBuilder):
    """Cloning volumes from existing."""

    def build_volume(self) -> types.Volume:
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        source_volume_id = self.volume_content_source.volume.volume_id
        if not (source_quota := self.vms_session.get_quota(source_volume_id)):
            raise SourceNotFound(f"Unknown volume: {source_volume_id}")

        source_path = source_quota.path
        tenant_id = source_quota.tenant_id
        snapshot_name = f"snp-{self.name}"
        snapshot_stream_name = f"strm-{self.name}"

        snapshot = self.vms_session.ensure_snapshot(
            snapshot_name=snapshot_name, path=source_path,
            tenant_id=tenant_id, expiration_delta=timedelta(minutes=5)
        )
        snapshot_stream = self.vms_session.ensure_snapshot_stream(
            snapshot_id=snapshot.id, destination_path=self.view_path, tenant_id=tenant_id,
            snapshot_stream_name=snapshot_stream_name,
        )
        # View should go after snapshot stream.
        # Otherwise, snapshot stream action will detect folder already exist and will be rejected
        view = self.vms_session.ensure_view(
            path=self.view_path, protocols=[self.mount_protocol],
            view_policy=self.view_policy, qos_policy=self.qos_policy
        )
        quota = self.vms_session.ensure_quota(
            volume_id=volume_name, view_path=self.view_path,
            tenant_id=view.tenant_id, requested_capacity=requested_capacity
        )
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
class VolumeFromSnapshotBuilder(BaseBuilder):
    """Builder for k8s Snapshots."""

    def build_volume(self) -> types.Volume:
        """
        Main entry point for snapshots.
        Create snapshot representation.
        """
        source_snapshot_id = self.volume_content_source.snapshot.snapshot_id
        if not (snapshot := self.vms_session.get_snapshot(snapshot_id=source_snapshot_id)):
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
            snapshot_stream = self.vms_session.ensure_snapshot_stream(
                snapshot_id=snapshot.id, destination_path=self.view_path, tenant_id=tenant_id,
                snapshot_stream_name=snapshot_stream_name,
            )
            view = self.vms_session.ensure_view(
                path=self.view_path, protocols=[self.mount_protocol],
                view_policy=self.view_policy, qos_policy=self.qos_policy
            )
            quota = self.vms_session.ensure_quota(
                volume_id=volume_name, view_path=self.view_path,
                tenant_id=view.tenant_id, requested_capacity=requested_capacity
            )
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
@dataclass
class StaticVolumeBuilder(BaseBuilder):
    create_view: bool = True
    create_quota: bool = True

    @classmethod
    def from_parameters(
            cls,
            conf,
            vms_session,
            name,
            volume_capabilities,
            parameters,
            create_view,
            create_quota,
    ):
        """Parse context and return builder instance"""
        mount_options = cls._parse_mount_options(volume_capabilities)
        rw_access_mode = cls._parse_access_mode(volume_capabilities)
        root_export = parameters["root_export"]
        # View policy is required only when view is about to be created.
        if not (view_policy := parameters.get("view_policy")) and create_view:
            raise MissingParameter(param="view_policy")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        volume_name_fmt = parameters.get("volume_name_fmt", conf.name_fmt)
        qos_policy = parameters.get("qos_policy")
        if "size" in parameters:
            required_bytes = int(parse_quantity(parameters["size"]))
            capacity_range = Bunch(required_bytes=required_bytes)
        else:
            capacity_range = None
        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            capacity_range=capacity_range,
            rw_access_mode=rw_access_mode,
            pvc_name=parameters.get("csi.storage.k8s.io/pvc/name"),
            pvc_namespace=parameters.get("csi.storage.k8s.io/pvc/namespace"),
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            mount_options=mount_options,
            qos_policy=qos_policy,
            create_view=create_view,
            create_quota=create_quota
        )

    @property
    def view_path(self):
        return self.root_export_abs

    def build_volume(self) -> dict:
        """
        Main build entrypoint for static volumes.
        Create volume from pvc, pv etc.
        """
        volume_name = self.build_volume_name()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        if self.create_view:
            # Check if view with expected system path already exists.
            view = self.vms_session.ensure_view(
                path=self.view_path, protocols=[self.mount_protocol],
                view_policy=self.view_policy, qos_policy=self.qos_policy
            )
        else:
            if not (view := self.vms_session.get_view(path=self.view_path)):
                raise SourceNotFound(f"View {self.view_path} does not exist but claimed as existing.")

        volume_context.update(view_id=str(view.id), tenant_id=str(view.tenant_id))

        if self.create_quota:
            quota = self.vms_session.ensure_quota(
                volume_id=volume_name, view_path=self.view_path,
                tenant_id=view.tenant_id, requested_capacity=self.get_requested_capacity()
            )
            volume_context.update(quota_id=str(quota.id))
        return volume_context


@final
class TestVolumeBuilder(BaseBuilder):
    """Test volumes builder for sanity checks"""

    @classmethod
    def from_parameters(
            cls,
            conf,
            vms_session,
            name,
            volume_capabilities,
            capacity_range,
            parameters,
            volume_content_source,
            **kwargs,
    ):
        rw_access_mode = cls._parse_access_mode(volume_capabilities)
        root_export = volume_name_fmt = view_policy = mount_options = ""
        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            capacity_range=capacity_range,
            rw_access_mode=rw_access_mode,
            volume_content_source=volume_content_source,
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            mount_options=mount_options,
        )

    def build_volume_name(self) -> str:
        pass

    def get_existing_capacity(self) -> Optional[int]:
        volume = self.vms_session.get_quota(self.name)
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

        vol_dir = self.vms_session._mock_mount[self.name]
        vol_dir.mkdir()

        volume = types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.name,
        )

        with self.configuration.fake_quota_store[self.name].open("wb") as f:
            f.write(volume.SerializeToString())
        return volume
