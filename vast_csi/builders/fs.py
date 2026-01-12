import os
from dataclasses import dataclass

from datetime import timedelta
from typing import Optional, final
from plumbum import local
from easypy.bunch import Bunch
from vast_csi import csi_types as types
from vast_csi.quantity import parse_quantity
from vast_csi.capabilities import Capabilities
from vast_csi.exceptions import SourceNotFound, MissingParameter
from vast_csi.builders.base import BaseVolumeBuilder, parse_volume_id


__all__ = [
    "EmptyVolumeBuilder",
    "VolumeFromVolumeBuilder",
    "VolumeFromSnapshotBuilder",
    "StaticVolumeBuilder",
]

@dataclass
class FileSystemProvisionBase(BaseVolumeBuilder):
    """Common builder with shared methods/attributes"""

    # Required parameters
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str  # Name of volume or snapshot
    root_export: str
    view_policy: str
    volume_capabilities: Capabilities

    # Optional parameters
    volume_name_fmt: Optional[str] = None
    ephemeral_volume_name: Optional[str] = None
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    vip_pool_fqdn_random_prefix: Optional[bool] = None
    qos_policy: Optional[str] = None
    qos_policy_id: Optional[int] = None
    blocking_clones: Optional[bool] = None
    capacity_range: Optional[int] = None  # Optional desired volume capacity
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None
    volume_content_source: Optional[types.VolumeContentSource] = None  # Either volume or snapshot

    @property
    def volume_context(self) -> dict:
        """Return the volume context dictionary."""
        context = {
            "root_export": self.root_export_abs,
            "mount_options": self.volume_capabilities.mount_flags_str,
            "view_policy": self.view_policy,
            "protocol": self.mount_protocol,
        }
        if self.vip_pool_name:
            context["vip_pool_name"] = self.vip_pool_name
        elif self.vip_pool_fqdn:
            context["vip_pool_fqdn"] = self.vip_pool_fqdn
            if self.vip_pool_fqdn_random_prefix:
                context["vip_pool_fqdn_random_prefix"] = "true"
        return context

    @property
    def view_path(self) -> str:
        """Return the full path to the view."""
        return os.path.join(self.root_export_abs, self.name)

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
    ) -> "FileSystemProvisionBase":
        """Parse context and return builder instance."""
        root_export = cls._get_required_param(parameters, "root_export")
        view_policy = cls._get_required_param(parameters, "view_policy")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix")
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)

        volume_name_fmt = parameters.get("volume_name_fmt", conf.name_fmt)
        qos_policy = parameters.get("qos_policy")
        cluster_name = parameters.get("cluster_name")
        blocking_clones = cls._get_bool_param(parameters, "blocking_clones")
        if "qos_policy_id" in parameters:
            qos_policy_id = int(parameters.get("qos_policy_id"))
        else:
            qos_policy_id = None

        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            volume_capabilities=volume_capabilities,
            capacity_range=capacity_range,
            volume_content_source=volume_content_source,
            ephemeral_volume_name=ephemeral_volume_name,
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            vip_pool_fqdn_random_prefix=vip_pool_fqdn_random_prefix,
            qos_policy=qos_policy,
            qos_policy_id=qos_policy_id,
            cluster_name=cluster_name,
            blocking_clones=blocking_clones,
            **cls._parse_metadata_from_params(parameters)
        )


# ----------------------------------------------------------------------------------------------------------------------
# Final builders
# ----------------------------------------------------------------------------------------------------------------------

@final
class EmptyVolumeBuilder(FileSystemProvisionBase):
    """Builder for k8s PersistentVolumeClaim, PersistentVolume etc."""

    def build_volume(self) -> types.Volume:
        """Main build entrypoint for volumes."""
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        view = self.vms_session.views.ensure(
            path=self.view_path,
            protocols=[self.mount_protocol],
            view_policy=self.view_policy,
            qos_policy=self.qos_policy,
            qos_policy_id=self.qos_policy_id,
        )
        quota = self.vms_session.quotas.ensure(
            volume_id=volume_name,
            view_path=self.view_path,
            tenant_id=view.tenant_id,
            requested_capacity=requested_capacity,
        )
        volume_context.update(
            quota_id=str(quota.id),
            view_id=str(view.id),
            tenant_id=str(view.tenant_id)
        )
        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.volume_id_with_metadata,
            volume_context=volume_context,
        )


@final
class VolumeFromVolumeBuilder(FileSystemProvisionBase):
    """Cloning volumes from existing."""

    def build_volume(self) -> types.Volume:
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        source_volume_id = self.volume_content_source.volume.volume_id
        # Source volume id without metadata
        orig_source_volume_id, _ = parse_volume_id(source_volume_id)

        if not (source_quota := self.vms_session.quotas.one(name=orig_source_volume_id)):
            raise SourceNotFound(f"Unknown volume: {orig_source_volume_id}")

        source_path = source_quota.path
        tenant_id = source_quota.tenant_id
        snapshot_name = f"snp-{self.name}"
        snapshot_stream_name = f"strm-{self.name}"

        snapshot = self.vms_session.snapshots.ensure(
            name=snapshot_name,
            path=source_path,
            tenant_id=tenant_id,
            expiration_delta=timedelta(minutes=5),
        )
        snapshot_stream = self.vms_session.globalsnapstreams.ensure(
            name=snapshot_stream_name,
            snapshot_id=snapshot.id,
            destination_path=self.view_path,
            tenant_id=tenant_id,
            wait=self.blocking_clones,
        )
        # View should go after snapshot stream.
        # Otherwise, snapshot stream action will detect folder already exist and will be rejected
        view = self.vms_session.views.ensure(
            path=self.view_path,
            protocols=[self.mount_protocol],
            view_policy=self.view_policy,
            qos_policy=self.qos_policy,
            qos_policy_id=self.qos_policy_id,
        )
        quota = self.vms_session.quotas.ensure(
            volume_id=volume_name,
            view_path=self.view_path,
            tenant_id=view.tenant_id,
            requested_capacity=requested_capacity,
        )
        volume_context.update(
            quota_id=str(quota.id),
            view_id=str(view.id),
            tenant_id=str(tenant_id),
            snapshot_stream_name=snapshot_stream.name,
        )
        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.volume_id_with_metadata,
            content_source=types.VolumeContentSource(
                volume=types.VolumeSource(volume_id=source_volume_id)
            ),
            volume_context=volume_context,
        )


@final
class VolumeFromSnapshotBuilder(FileSystemProvisionBase):
    """VolumeBuilder based on snapshot."""

    def build_volume(self) -> types.Volume:
        source_snapshot_id = self.volume_content_source.snapshot.snapshot_id
        # source snapshot id without metadata
        orig_source_snapshot_id, _ = parse_volume_id(source_snapshot_id)
        if not (snapshot := self.vms_session.snapshots.get(orig_source_snapshot_id)):
            raise SourceNotFound(f"Unknown snapshot: {orig_source_snapshot_id}")
        volume_context = self.volume_context

        if self.volume_capabilities.rw_mode:
            # Create volume from snapshot for READ_WRITE modes.
            #   quota and view will be created.
            #   The contents of the source snapshot will be replicated to view folder
            #   using an intermediate global snapshot stream.
            tenant_id = snapshot.tenant_id
            volume_name = self.build_volume_name()
            requested_capacity = self.get_requested_capacity()
            volume_context["volume_name"] = volume_name

            snapshot_stream_name = f"strm-{self.name}"
            snapshot_stream = self.vms_session.globalsnapstreams.ensure(
                name=snapshot_stream_name,
                snapshot_id=snapshot.id,
                destination_path=self.view_path,
                tenant_id=tenant_id,
                wait=self.blocking_clones,
            )
            view = self.vms_session.views.ensure(
                path=self.view_path,
                protocols=[self.mount_protocol],
                view_policy=self.view_policy,
                qos_policy=self.qos_policy,
                qos_policy_id=self.qos_policy_id,
            )
            quota = self.vms_session.quotas.ensure(
                volume_id=volume_name,
                view_path=self.view_path,
                tenant_id=view.tenant_id,
                requested_capacity=requested_capacity
            )
            volume_context.update(
                quota_id=str(quota.id),
                view_id=str(view.id),
                tenant_id=str(tenant_id),
                snapshot_stream_name=snapshot_stream.name
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
            volume_id=self.volume_id_with_metadata,
            content_source=types.VolumeContentSource(
                snapshot=types.SnapshotSource(snapshot_id=source_snapshot_id)
            ),
            volume_context=volume_context
        )


@final
@dataclass
class StaticVolumeBuilder(BaseVolumeBuilder):
    # Required parameters
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str
    root_export: str
    view_policy: str
    volume_capabilities: Capabilities

    # Optional parameters
    volume_name_fmt: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    vip_pool_fqdn_random_prefix: Optional[bool] = None
    qos_policy: Optional[str] = None
    qos_policy_id: Optional[int] = None
    capacity_range: Optional[int] = None  # Optional desired volume capacity
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None
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
        root_export = parameters["root_export"]
        # View policy is required only when view is about to be created.
        if not (view_policy := parameters.get("view_policy")) and create_view:
            raise MissingParameter(param="view_policy")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix")
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        volume_name_fmt = parameters.get("volume_name_fmt", conf.name_fmt)
        qos_policy = parameters.get("qos_policy")
        if "size" in parameters:
            required_bytes = int(parse_quantity(parameters["size"]))
            capacity_range = Bunch(required_bytes=required_bytes)
        else:
            capacity_range = None
        if "qos_policy_id" in parameters:
            qos_policy_id = int(parameters.get("qos_policy_id"))
        else:
            qos_policy_id = None

        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            capacity_range=capacity_range,
            volume_capabilities=volume_capabilities,
            root_export=root_export,
            volume_name_fmt=volume_name_fmt,
            view_policy=view_policy,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            vip_pool_fqdn_random_prefix=vip_pool_fqdn_random_prefix,
            qos_policy=qos_policy,
            qos_policy_id=qos_policy_id,
            create_view=create_view,
            create_quota=create_quota,
            **cls._parse_metadata_from_params(parameters)
        )

    @property
    def view_path(self):
        return self.root_export_abs

    @property
    def volume_context(self) -> dict:
        """Return the volume context dictionary."""
        context = {
            "root_export": self.root_export_abs,
            "mount_options": self.volume_capabilities.mount_flags_str,
            "view_policy": self.view_policy,
            "protocol": self.mount_protocol,
        }
        if self.vip_pool_name:
            context["vip_pool_name"] = self.vip_pool_name
        elif self.vip_pool_fqdn:
            context["vip_pool_fqdn"] = self.vip_pool_fqdn
            if self.vip_pool_fqdn_random_prefix:
                context["vip_pool_fqdn_random_prefix"] = "true"
        return context

    def build_volume(self) -> dict:
        """
        Main build entrypoint for static volumes.
        Create volume from pvc, pv etc.
        """
        volume_name = self.build_volume_name()
        volume_context = self.volume_context
        volume_context["volume_name"] = volume_name

        view = None
        if self.create_view:
            # Check if view with expected system path already exists.
            view = self.vms_session.views.ensure(
                path=self.view_path,
                protocols=[self.mount_protocol],
                view_policy=self.view_policy,
                qos_policy=self.qos_policy,
                qos_policy_id=self.qos_policy_id,
            )

        if self.create_quota:
            if not view:
                if not (view := self.vms_session.views.one(path=self.view_path)):
                    raise SourceNotFound(f"View {self.view_path} does not exist but claimed as existing.")

            quota = self.vms_session.quotas.ensure(
                volume_id=volume_name,
                view_path=self.view_path,
                tenant_id=view.tenant_id,
                requested_capacity=self.get_requested_capacity(),
            )
            volume_context.update(quota_id=str(quota.id))

        if view:
            volume_context.update(view_id=str(view.id), tenant_id=str(view.tenant_id))

        return volume_context
