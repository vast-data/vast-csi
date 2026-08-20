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

    # Optional parameters
    tenant_name: Optional[str] = None
    volume_group: Optional[str] = None
    transport_type: Optional[str] = None
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    vip_pool_fqdn_random_prefix: Optional[bool] = None
    qos_policy: Optional[str] = None
    qos_policy_id: Optional[int] = None
    blocking_clones: Optional[bool] = None
    host_nqn_obfuscation: Optional[bool] = None
    capacity_range: Optional[int] = None
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None
    host_encryption: Optional[dict] = None
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
        tenant_name = parameters.get("tenant_name")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix", default_value="true")
        volume_group = parameters.get("volume_group", "")
        host_encryption = cls._parse_host_encryption(parameters)
        transport_type = parameters.get("transport_type", "TCP").upper()
        metadata = cls._parse_metadata_from_params(parameters)
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        cluster_name = parameters.get("cluster_name")
        blocking_clones = cls._get_bool_param(parameters, "blocking_clones")
        host_nqn_obfuscation = cls._get_bool_param(parameters, "host_nqn_obfuscation")
        qos_policy = parameters.get("qos_policy")
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
            subsystem=subsystem,
            tenant_name=tenant_name,
            transport_type=transport_type,
            volume_group=volume_group,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            host_encryption=host_encryption,
            vip_pool_fqdn_random_prefix=vip_pool_fqdn_random_prefix,
            cluster_name=cluster_name,
            qos_policy_id=qos_policy_id,
            qos_policy=qos_policy,
            volume_content_source=volume_content_source,
            blocking_clones=blocking_clones,
            host_nqn_obfuscation=host_nqn_obfuscation,
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
        return os.path.join("/", volume_group, self.name).lstrip("/")


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
            context["vip_pool_fqdn"] = self.vip_pool_fqdn
            if self.vip_pool_fqdn_random_prefix:
                context["vip_pool_fqdn_random_prefix"] = "true"
        if self.host_encryption:
            context[f"host_encryption"] = json.dumps(self.host_encryption)
        if self.host_nqn_obfuscation:
            context["host_nqn_obfuscation"] = "true"
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
        view = self.vms_session.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        qos_policy_id = self.qos_policy_id
        if self.qos_policy:
            qos_policy_id = self.vms_session.quospolicies.one(
                name=self.qos_policy,
                fail_if_missing=True,
            ).id
        volume_data = dict(
            name=volume_name,
            view_id=view.id,
            size=requested_capacity,
        )
        if qos_policy_id:
            volume_data["qos_policy_id"] = qos_policy_id
        volume = self.vms_session.volumes.ensure(**volume_data)
        volume_context.update(
            nguid=volume.nguid,
            volume_id=str(volume.id),
            tenant_name=view.tenant_name,
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
        if not (source_view := self.vms_session.views.get_subsystem_by_id(_id=source_volume.view_id)):
            raise SourceNotFound(f"Unknown subsystem: {source_volume.view_id}")

        volume_context = self.volume_context
        tenant_id = source_view.tenant_id
        tenant_name = source_view.tenant_name
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context["volume_name"] = volume_name

        # Concatenation of source subsystem path and source volume name
        source_path = os.path.join(source_view.path, source_volume.name.lstrip("/"))
        if source_view.name != self.subsystem:
            # Query destination subsystem if it differs from the source subsystem
            destination_view = self.vms_session.views.get_subsystem(
                subsystem=self.subsystem,
                tenant_name=self.tenant_name,
            )
        else:
            # No need to perform additional VMS call if source and destination subsystems are the same
            destination_view = source_view

        if not (destination_volume := self.vms_session.volumes.one(name__endswith=volume_name)):
            # Create an intermediate snapshot with limited expiration time
            snapshot_name = f"snp-{self.name}"
            snapshot = self.vms_session.snapshots.ensure(
                name=snapshot_name,
                path=source_path,
                tenant_id=tenant_id,
                expiration_delta=timedelta(minutes=5),
            )
            destination_volume = self.vms_session.snapshots.clone_volume(
                snapshot_id=snapshot.id,
                target_subsystem_id=destination_view.id,
                target_volume_path=volume_name,
            )
            qos_policy_id = self.qos_policy_id
            if self.qos_policy:
                qos_policy_id = self.vms_session.quospolicies.one(
                    name=self.qos_policy,
                    fail_if_missing=True,
                ).id
            if qos_policy_id:
                self.vms_session.volumes.update(
                    destination_volume.id,
                    qos_policy_id=qos_policy_id,
                )

        if self.blocking_clones:
            # Wait for the clone to be ready
            destination_path = os.path.join(destination_view.path, destination_volume.name.lstrip("/"))
            self.vms_session.globalsnapstreams.wait_by_loanee_path(loanee_root_path=destination_path)

        if requested_capacity > destination_volume.size:
            self.vms_session.volumes.update(destination_volume.id, size=requested_capacity)
            # For cloned filesystem volumes need to perform local resizing
            if self.volume_capabilities.is_filesystem:
                volume_context.update(need_resize="true")

        volume_context.update(
            nguid=destination_volume.nguid,
            volume_id=str(destination_volume.id),
            tenant_name=tenant_name,
            subsystem_nqn=destination_view.nqn,
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

        volume_context = self.volume_context
        volume_name = self.build_volume_name()
        requested_capacity = self.get_requested_capacity()
        volume_context["volume_name"] = volume_name

        destination_view = self.vms_session.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        if not (destination_volume := self.vms_session.volumes.one(name__endswith=volume_name)):
            destination_volume = self.vms_session.snapshots.clone_volume(
                snapshot_id=snapshot.id,
                target_subsystem_id=destination_view.id,
                target_volume_path=volume_name,
            )
            qos_policy_id = self.qos_policy_id
            if self.qos_policy:
                qos_policy_id = self.vms_session.quospolicies.one(
                    name=self.qos_policy,
                    fail_if_missing=True,
                ).id
            if qos_policy_id:
                self.vms_session.volumes.update(
                    destination_volume.id,
                    qos_policy_id=qos_policy_id,
                )

        if self.blocking_clones:
            # Wait for the clone to be ready
            destination_path = os.path.join(destination_view.path, destination_volume.name.lstrip("/"))
            self.vms_session.globalsnapstreams.wait_by_loanee_path(loanee_root_path=destination_path)

        if requested_capacity > destination_volume.size:
            self.vms_session.volumes.update(destination_volume.id, size=requested_capacity)
            # For cloned filesystem volumes need to perform local resizing
            if self.volume_capabilities.is_filesystem:
                volume_context.update(need_resize="true")

        volume_context.update(
            nguid=destination_volume.nguid,
            volume_id=str(destination_volume.id),
            tenant_name=snapshot.tenant_name,
            subsystem_nqn=destination_view.nqn,
        )
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
class StaticBlockVolumeBuilder(BaseVolumeBuilder):
    # Required parameters
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str
    volume_capabilities: Capabilities
    subsystem: str

    # Optional parameters
    tenant_name: Optional[str] = None
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    vip_pool_fqdn_random_prefix: Optional[bool] = None
    host_encryption: Optional[dict] = None
    host_nqn_obfuscation: Optional[bool] = None
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
        tenant_name = parameters.get("tenant_name")
        vip_pool_fqdn = parameters.get("vip_pool_fqdn")
        vip_pool_name = parameters.get("vip_pool_name")
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix", default_value="true")
        transport_type = parameters.get("transport_type", "TCP").upper()
        host_encryption = cls._parse_host_encryption(parameters)
        host_nqn_obfuscation = cls._get_bool_param(parameters, "host_nqn_obfuscation")
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        cluster_name = parameters.get("cluster_name")
        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            subsystem=subsystem,
            tenant_name=tenant_name,
            volume_capabilities=volume_capabilities,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            vip_pool_fqdn_random_prefix=vip_pool_fqdn_random_prefix,
            transport_type=transport_type,
            cluster_name=cluster_name,
            host_encryption=host_encryption,
            host_nqn_obfuscation=host_nqn_obfuscation,
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
            context["vip_pool_fqdn"] = self.vip_pool_fqdn
            if self.vip_pool_fqdn_random_prefix:
                context["vip_pool_fqdn_random_prefix"] = "true"
        if self.host_encryption:
            context[f"host_encryption"] = json.dumps(self.host_encryption)
        if self.host_nqn_obfuscation:
            context["host_nqn_obfuscation"] = "true"
        return context

    def build_volume(self) -> types.Volume:
        name = self.name.lstrip("/")
        volume_context = self.volume_context
        view = self.vms_session.views.get_subsystem(
            subsystem=self.subsystem,
            tenant_name=self.tenant_name,
        )
        if not (volume := self.vms_session.volumes.one(name=name)):
            raise SourceNotFound(f"Volume {name} does not exist but claimed as existing.")
        volume_context.update(
            nguid=volume.nguid,
            volume_id=str(volume.id),
            tenant_name=view.tenant_name,
            subsystem_nqn=view.nqn,
        )
        return volume_context
