import os
import json
from datetime import timedelta
from dataclasses import dataclass
from typing import final, Optional

from vast_csi import csi_types as types
from vast_csi.exceptions import SourceNotFound
from vast_csi.capabilities import Capabilities
from vast_csi.builders.base import BaseVolumeBuilder, parse_volume_id


__all__ = [
    "EmptyBlockVolumeBuilder",
    "BlockVolumeFromVolumeBuilder",
    "BlockVolumeFromSnapshotBuilder",
]


@dataclass
class BlockProvisionBase(BaseVolumeBuilder):
    """Common builder with shared methods/attributes"""

    vms_session: "RESTSession"
    configuration: "CONF"
    name: str
    volume_capabilities: Capabilities
    subsystem: str
    volume_group: str = None
    volume_tags: dict = None
    transport_type: str = None

    # Optional parameters
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    capacity_range: Optional[int] = None
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None
    volume_content_source: Optional[types.VolumeContentSource] = None  # Either volume or snapshot

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
    ) -> "BaseBuilder":
        """Parse context and return builder instance."""
        subsystem = cls._get_required_param(parameters, "subsystem")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        volume_group = parameters.get("volume_group", "")
        transport_type = parameters.get("transport_type", "TCP").upper()
        volume_tags = json.loads(parameters.get("volume_tags", "{}"))
        metadata = cls._parse_metadata_from_params(parameters)
        if metadata.pvc_name and metadata.pvc_namespace:
            volume_tags.update({
                "block.csi.vastdata.com/pvc_name": metadata.pvc_name,
                "block.csi.vastdata.com/pvc_namespace": metadata.pvc_namespace,
            })
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        cluster_name = parameters.get("cluster_name")

        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            volume_capabilities=volume_capabilities,
            capacity_range=capacity_range,
            subsystem=subsystem,
            transport_type=transport_type,
            volume_group=volume_group,
            volume_tags=volume_tags,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            cluster_name=cluster_name,
            volume_content_source=volume_content_source,
            **metadata,
        )

    def build_volume_name(self) -> str:
        """
        Build the volume name based on the provided volume_group template.
        The volume group is constructed using a template that can include placeholders for
        the PVC namespace, PVC name, and volume ID. The placeholders are specified using
        the syntax `{namespace}`, `{name}`, and `{id}` in the template.
        The volume group name can represent nested folders. It is the user's responsibility
        to provide a multi-folder template (e.g., `/folder1/folder2/block-{namespace}-{id}`)
        if nested folder structures are desired.

        Example:
            If the `pvc_name = "my-pvc"`, `pvc_namespace = "default"`, and `volume_group = "/vol/{namespace}/{name}/{id}"`,
            and the `name = "volume123"`, the result would be:
                "/vol/default/my-pvc/volume123"
        """
        volume_group = self.volume_group
        if self.pvc_name and self.pvc_namespace:
            volume_group = volume_group.format(
                namespace=self.pvc_namespace, name=self.pvc_name
            )
        # make sure the volume group is a valid absolute path
        return os.path.join("/", volume_group, self.name)

    @property
    def volume_context(self) -> dict:
        context = {
            "subsystem": self.subsystem,
            "transport_type": self.transport_type,
        }
        if self.volume_capabilities.mount_flags_str:
            context["mount_options"] = self.volume_capabilities.mount_flags_str
        if self.vip_pool_name:
            context["vip_pool_name"] = self.vip_pool_name
        elif self.vip_pool_fqdn:
            context["vip_pool_fqdn"] = self.vip_pool_fqdn_with_prefix
        return context


@final
class EmptyBlockVolumeBuilder(BlockProvisionBase):

    def build_volume(self) -> types.Volume:
        """Main build entrypoint for volumes."""
        requested_capacity = self.get_requested_capacity()
        volume_name = self.build_volume_name()
        # volume group must contain volume id despite how nested it is.
        # volume id is used to delete volume.
        volume_context = self.volume_context
        view = self.vms_session.views.get_subsystem(subsystem=self.subsystem)
        volume = self.vms_session.volumes.ensure(
            name=volume_name,
            view_id=view.id,
            size=requested_capacity,
            tags=self.volume_tags,
        )
        volume_context.update(
            nguid=volume.nguid,
            volume_id=str(volume.id),
            tenant_id=str(view.tenant_id),
            subsystem_nqn=view.nqn,
        )
        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.volume_id_with_metadata,
            volume_context=volume_context,
        )


@final
class BlockVolumeFromVolumeBuilder(BlockProvisionBase):
    """Cloning volumes from existing."""

    def build_volume(self) -> types.Volume:
        source_volume_id = self.volume_content_source.volume.volume_id
        # Source volume id without metadata
        orig_source_volume_id, _ = parse_volume_id(source_volume_id)
        if not (source_volume := self.vms_session.volumes.one(name__endswith=orig_source_volume_id)):
            raise SourceNotFound(f"Unknown volume: {orig_source_volume_id}")
        if not (source_view := self.vms_session.views.get_subsystem(_id=source_volume.view_id)):
            raise SourceNotFound(f"Unknown subsystem: {source_volume.view_id}")

        volume_context = self.volume_context
        tenant_id = source_view.tenant_id
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context["volume_name"] = volume_name

        # Concatenation of source subsystem path and source volume name
        source_path = os.path.join(source_view.path, source_volume.name.lstrip("/"))

        if source_view.name != self.subsystem:
            destination_view = self.vms_session.views.get_subsystem(subsystem=self.subsystem)
        else:
            # No need to perform additional VMS call if source and destination subsystems are the same
            destination_view = source_view
        # Concatenation of destination subsystem path and volume name
        destination_path = os.path.join(destination_view.path, volume_name.lstrip("/"))

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
            destination_path=destination_path,
            tenant_id=tenant_id,
        )
        volume = self.vms_session.volumes.ensure(
            name=volume_name,
            view_id=destination_view.id,
            size=requested_capacity,
            tags=self.volume_tags,
        )
        volume_context.update(
            uuid=volume.uuid,
            volume_id=str(volume.id),
            tenant_id=str(tenant_id),
            subsystem_nqn=destination_view.nqn,
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
class BlockVolumeFromSnapshotBuilder(BlockProvisionBase):
    """VolumeBuilder based on snapshot."""

    def build_volume(self) -> types.Volume:
        source_snapshot_id = self.volume_content_source.snapshot.snapshot_id
        # source snapshot id without metadata
        orig_source_snapshot_id, _ = parse_volume_id(source_snapshot_id)
        if not (snapshot := self.vms_session.snapshots.get(orig_source_snapshot_id)):
            raise SourceNotFound(f"Unknown snapshot: {orig_source_snapshot_id}")
        # TODO: should validate self.volume_capabilities.rw_mode ? Can we create a volume from a snapshot with ro mode?

        volume_context = self.volume_context
        tenant_id = snapshot.tenant_id
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context["volume_name"] = volume_name

        view = self.vms_session.views.get_subsystem(subsystem=self.subsystem)
        # Concatenation of subsystem path and volume name
        destination_path = os.path.join(view.path, volume_name.lstrip("/"))
        snapshot_stream_name = f"strm-{self.name}"
        snapshot_stream = self.vms_session.globalsnapstreams.ensure(
            name=snapshot_stream_name,
            snapshot_id=snapshot.id,
            destination_path=destination_path,
            tenant_id=tenant_id,
        )
        volume = self.vms_session.volumes.ensure(
            name=volume_name,
            view_id=view.id,
            size=requested_capacity,
            tags=self.volume_tags,
        )
        volume_context.update(
            uuid=volume.uuid,
            volume_id=str(volume.id),
            tenant_id=str(tenant_id),
            subsystem_nqn=view.nqn,
            snapshot_stream_name=snapshot_stream.name,
        )
        return types.Volume(
            capacity_bytes=requested_capacity,
            volume_id=self.volume_id_with_metadata,
            content_source=types.VolumeContentSource(
                snapshot=types.SnapshotSource(snapshot_id=source_snapshot_id)
            ),
            volume_context=volume_context
        )
