import os
import json
from abc import ABC
from typing import Optional, TypeVar, Tuple
from vast_csi.csi_types import INVALID_ARGUMENT
from easypy.bunch import Bunch
from easypy.humanize import yesno_to_bool

from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.utils import is_valid_ip, get_random_fqdn_prefix, is_ver_nfs4_present


CreatedVolumeT = TypeVar("CreatedVolumeT")
VOLUME_ID_SEPARATOR = "@"


__all__ = [
    "BaseVolumeBuilder",
    "parse_volume_id",
    "to_volume_id_with_metadata",
]


def parse_volume_id(volume_id: str) -> Tuple[str, Optional[str]]:
    """Parses the volume ID into a name and optional cluster name.
    Args:
        volume_id (str): The volume ID in the format `volume_name@cluster_name`.
    Returns:
        Tuple[str, Optional[str]]: A tuple containing the volume name and cluster name.
        If the cluster name is not present, it returns `None` as the second element.
    """
    parts = volume_id.split(VOLUME_ID_SEPARATOR)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]


def to_volume_id_with_metadata(volume_id: str, cluster_name: Optional[str]) -> str:
    """Appends the cluster name to the volume ID, if provided.
    Args:
        volume_id (str): The base volume ID.
        cluster_name (Optional[str]): The cluster name to append. If `None`, no cluster name is added.
    Returns:
        str: The volume ID with the appended cluster name, or the original volume ID if no cluster name is provided.
    """
    return f"{volume_id}{VOLUME_ID_SEPARATOR}{cluster_name}" if cluster_name else str(volume_id)


class VolumeBuilderI(ABC):
    """Interface for all volume builders.
    Defines the methods required for building volumes, which include operations
    such as constructing names, managing capacity, and building the volume itself.
    """

    def build_volume_name(self, **kwargs) -> str:
        """Constructs the volume name based on the provided arguments.
        Args:
            **kwargs: Additional parameters for constructing the volume name.
        Returns:
            str: The constructed volume name.
        """
        ...

    def get_requested_capacity(self) -> int:
        """Retrieves the requested capacity for the volume.
        Returns:
            int: The requested capacity in bytes.
        """
        ...

    def get_existing_capacity(self) -> int:
        """Retrieves the existing capacity of the volume.
        Returns:
            int: The existing capacity in bytes.
        """
        ...

    def build_volume(self, **kwargs) -> CreatedVolumeT:
        """Performs the final steps to build or prepare the volume for creation.
        Args:
            **kwargs: Additional parameters for building the volume.
        Returns:
            CreatedVolumeT: The created volume instance or relevant data for the build process.
        """
        ...

    @classmethod
    def from_parameters(cls, *args, **kwargs):
        """Creates a volume builder instance using the provided parameters.
        Args:
            *args: Positional arguments for initializing the builder.
            **kwargs: Keyword arguments for initializing the builder.
        Returns:
            VolumeBuilderI: An instance of the implementing volume builder class.
        """
        ...

    @classmethod
    def build(cls, *args, **kwargs) -> CreatedVolumeT:
        """
       Creates a volume from provide arguments.
       Initializes a builder with the given parameters and invokes `build_volume`
       to construct the volume.
       """
        builder = cls.from_parameters(*args, **kwargs)
        return builder.build_volume()


class CommonPropsMixin:

    @property
    def mount_protocol(self) -> str:
        """Return the mount protocol based on the volume capabilities."""
        return "NFS4" if is_ver_nfs4_present(self.volume_capabilities.mount_flags) else "NFS"

    @property
    def root_export_abs(self) -> str:
        """Return the absolute path for the root export."""
        return os.path.join("/", self.root_export)

    @property
    def volume_id_with_metadata(self):
        """Return the volume ID with metadata."""
        return to_volume_id_with_metadata(self.name, self.cluster_name)

    def get_requested_capacity(self) -> int:
        """Return desired allocated capacity if provided, else return 0."""
        return self.capacity_range.required_bytes if self.capacity_range else 0

    def build_volume_name(self) -> str:
        """Build volume name using format csi:{id}:{namespace}:{name}"""
        volume_id = self.name
        if ephemeral_volume_name := getattr(self, "ephemeral_volume_name", None):
            return ephemeral_volume_name

        if self.pvc_name and self.pvc_namespace:
            volume_name = self.volume_name_fmt.format(
                namespace=self.pvc_namespace, name=self.pvc_name, id=volume_id
            )
        else:
            volume_name = f"csi-{volume_id}"

        if self.configuration.truncate_volume_name:
            volume_name = volume_name[:self.configuration.truncate_volume_name]

        return volume_name


class BaseVolumeBuilder(CommonPropsMixin, VolumeBuilderI):
    """Base builder with common parsing and validation methods for all volume builders."""

    @classmethod
    def _get_required_param(cls, parameters, param_name):
        """Get required parameter or raise MissingParameter exception."""
        value = parameters.get(param_name)
        if value is None:
            raise MissingParameter(param=param_name)
        return value

    @classmethod
    def _get_bool_param(cls, parameters, param_name, default_value="false"):
        """Get boolean parameter from parameters or return default value."""
        if param_name not in parameters:
            return yesno_to_bool(str(default_value))
        return yesno_to_bool(str(parameters[param_name]))

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

    @classmethod
    def _parse_metadata_from_params(cls, params):
        """
        pvc metadata is extracted for each type of builder
        This method is convenient wrapper to extract pvc metadata from params
        """
        return Bunch(
            pvc_name=params.get("csi.storage.k8s.io/pvc/name"),
            pvc_namespace=params.get("csi.storage.k8s.io/pvc/namespace"),
        )

    @staticmethod
    def _parse_host_encryption(params):
        host_encryption = params.get("host_encryption", {})
        if isinstance(host_encryption, str):
            host_encryption = json.loads(host_encryption)
        return host_encryption
