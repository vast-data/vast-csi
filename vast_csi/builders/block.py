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
    "StaticBlockVolumeBuilder",
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
@dataclass
class StaticBlockVolumeBuilder(BaseVolumeBuilder):
    # Required parameters
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str
    volume_capabilities: Capabilities
    subsystem: str

    # Optional parameters
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    transport_type: Optional[str] = "TCP"

    @classmethod
    def from_parameters(
            cls,
            conf,
            vms_session,
            name,
            volume_capabilities,
            parameters,
    ):
        """Parse context and return builder instance"""
        subsystem = cls._get_required_param(parameters, "subsystem")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        transport_type = parameters.get("transport_type", "TCP").upper()
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        cluster_name = parameters.get("cluster_name")
        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            subsystem=subsystem,
            volume_capabilities=volume_capabilities,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            transport_type=transport_type,
            cluster_name=cluster_name,
        )

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

    def build_volume(self) -> types.Volume:
        volume_context = self.volume_context
        if not (view := self.vms_session.views.get_subsystem(subsystem=self.subsystem)):
            raise SourceNotFound(f"View {self.subsystem} does not exist but claimed as existing.")
        if not (volume := self.vms_session.volumes.one(name=self.name)):
            raise SourceNotFound(f"Volume {self.name} does not exist but claimed as existing.")
        volume_context.update(
            uuid=volume.uuid,
            volume_id=str(volume.id),
            tenant_id=str(view.tenant_id),
            subsystem_nqn=view.nqn,
        )
        return volume_context
