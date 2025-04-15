from dataclasses import dataclass
from typing import final, Optional

import vast_csi.csi_types as types
from vast_csi.builders.base import BaseVolumeBuilder
from vast_csi.capabilities import Capabilities
from vast_csi.exceptions import VolumeAlreadyExists, SourceNotFound


@final
@dataclass
class TestVolumeBuilder(BaseVolumeBuilder):
    """Test volumes builder for sanity checks"""

    # Required parameters
    vms_session: "RESTSession"
    configuration: "CONF"
    name: str  # Name of volume or snapshot
    root_export: str
    view_policy: str
    volume_capabilities: Capabilities

    # Optional parameters
    volume_name_fmt: Optional[str] = None
    volume_content_source: Optional[str] = None  # Either volume or snapshot
    ephemeral_volume_name: Optional[str] = None
    cluster_name: Optional[str] = None
    vip_pool_name: Optional[str] = None
    vip_pool_fqdn: Optional[str] = None
    volume_encryption: Optional[str] = None
    qos_policy: Optional[str] = None
    capacity_range: Optional[int] = None  # Optional desired volume capacity
    pvc_name: Optional[str] = None
    pvc_namespace: Optional[str] = None

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
        root_export = view_policy = ""
        return cls(
            vms_session=vms_session,
            configuration=conf,
            name=name,
            capacity_range=capacity_range,
            volume_capabilities=volume_capabilities,
            volume_content_source=volume_content_source,
            root_export=root_export,
            view_policy=view_policy,
        )

    def build_volume_name(self) -> str:
        pass

    def get_existing_capacity(self) -> Optional[int]:
        volume = self.vms_session.quotas.one(self.name)
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
