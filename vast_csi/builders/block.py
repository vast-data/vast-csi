import os
import json
import string
from datetime import timedelta
from dataclasses import dataclass
from typing import final, Optional

from vast_csi.csi_types import INVALID_ARGUMENT
from vast_csi import csi_types as types
from vast_csi.exceptions import Abort, SourceNotFound
from vast_csi.capabilities import Capabilities
from vast_csi.builders.base import BaseVolumeBuilder, parse_volume_id


_ALLOWED_VOLUME_NAME_FMT_FIELDS = frozenset({"id", "namespace", "name"})


def _validate_volume_name_fmt(fmt: str) -> None:
    """Validate ``volume_name_fmt`` template used for the Block basename.

    The format string is interpolated with ``{id}``, ``{namespace}`` and
    ``{name}`` placeholders. ``{id}`` is required so that lifecycle lookups
    using ``name__contains=<csi_id>`` (DeleteVolume, CreateSnapshot,
    ControllerExpandVolume, ControllerUnpublishVolume) keep working for
    volumes provisioned with a custom name template.
    """
    if not fmt:
        return
    try:
        fields = {
            field_name
            for _, field_name, _, _ in string.Formatter().parse(fmt)
            if field_name is not None
        }
    except ValueError as exc:
        raise Abort(INVALID_ARGUMENT, f"Invalid volume_name_fmt template: {exc}")
    unknown = fields - _ALLOWED_VOLUME_NAME_FMT_FIELDS
    if unknown:
        raise Abort(
            INVALID_ARGUMENT,
            f"volume_name_fmt contains unsupported placeholders: {sorted(unknown)}. "
            f"Allowed placeholders: {sorted(_ALLOWED_VOLUME_NAME_FMT_FIELDS)}.",
        )
    if "id" not in fields:
        raise Abort(
            INVALID_ARGUMENT,
            "volume_name_fmt must contain the {id} placeholder so that the CSI "
            "volume id can be located in the resulting VAST volume name.",
        )


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
    volume_name_fmt: Optional[str] = None
    transport_type: Optional[str] = None
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    vip_pool_fqdn_random_prefix: Optional[bool] = None
    qos_policy: Optional[str] = None
    qos_policy_id: Optional[int] = None
    blocking_clones: Optional[bool] = None
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
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix")
        volume_group = parameters.get("volume_group", "")
        volume_name_fmt = parameters.get("volume_name_fmt", "")
        _validate_volume_name_fmt(volume_name_fmt)
        host_encryption = cls._parse_host_encryption(parameters)
        transport_type = parameters.get("transport_type", "TCP").upper()
        metadata = cls._parse_metadata_from_params(parameters)
        cls._validate_mount_src(vip_pool_name, vip_pool_fqdn, conf.use_local_ip_for_mount)
        cluster_name = parameters.get("cluster_name")
        blocking_clones = cls._get_bool_param(parameters, "blocking_clones")
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
            volume_name_fmt=volume_name_fmt,
            vip_pool_name=vip_pool_name,
            vip_pool_fqdn=vip_pool_fqdn,
            host_encryption=host_encryption,
            vip_pool_fqdn_random_prefix=vip_pool_fqdn_random_prefix,
            cluster_name=cluster_name,
            qos_policy_id=qos_policy_id,
            qos_policy=qos_policy,
            volume_content_source=volume_content_source,
            blocking_clones=blocking_clones,
            **metadata,
        )

    def build_volume_name(self) -> str:
        """Build the VAST volume name from ``volume_group`` and ``volume_name_fmt``.

        - ``volume_group`` is an optional path prefix supporting ``{namespace}``
          and ``{name}`` placeholders. It can represent nested folders.
        - ``volume_name_fmt`` is an optional template for the basename
          (final path segment) supporting ``{id}``, ``{namespace}`` and
          ``{name}`` placeholders. When empty, the basename defaults to
          ``self.name`` (today's behavior), which is the CSI-generated volume id.

        The final VAST volume name is ``<volume_group>/<basename>``. Lifecycle
        lookups locate the volume via ``name__contains=<csi_id>``, which
        requires ``{id}`` to appear in ``volume_name_fmt`` when it is set
        (enforced at parse time by ``_validate_volume_name_fmt``).

        Examples:
            volume_group="vol/{namespace}/{name}", volume_name_fmt=""
                -> "vol/default/my-pvc/<csi_id>"
            volume_group="",                      volume_name_fmt="csi-{namespace}-{name}-{id}"
                -> "csi-default-my-pvc-<csi_id>"
            volume_group="vol/{namespace}",       volume_name_fmt="csi-{name}-{id}"
                -> "vol/default/csi-my-pvc-<csi_id>"
        """
        csi_id = self.name
        if self.volume_name_fmt and self.pvc_name and self.pvc_namespace:
            basename = self.volume_name_fmt.format(
                namespace=self.pvc_namespace, name=self.pvc_name, id=csi_id,
            )
        else:
            basename = csi_id

        volume_group = self.volume_group or ""
        if volume_group and self.pvc_name and self.pvc_namespace:
            volume_group = volume_group.format(
                namespace=self.pvc_namespace, name=self.pvc_name,
            )
        # make sure the volume name is a valid relative path
        return os.path.join("/", volume_group, basename).lstrip("/")


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
        if not (source_volume := self.vms_session.volumes.one(name__contains=orig_source_volume_id)):
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

        if not (destination_volume := self.vms_session.volumes.one(name=volume_name)):
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
        if not (destination_volume := self.vms_session.volumes.one(name=volume_name)):
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
        vip_pool_fqdn_random_prefix = cls._get_bool_param(parameters, "vip_pool_fqdn_random_prefix")
        transport_type = parameters.get("transport_type", "TCP").upper()
        host_encryption = cls._parse_host_encryption(parameters)
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
