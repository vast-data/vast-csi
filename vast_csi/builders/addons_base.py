import os
from abc import ABC
from easypy.humanize import yesno_to_bool

from vast_csi.exceptions import MissingParameter


__all__ = ["VolumeAddonsBuilderI"]


class VolumeAddonsBuilderI(ABC):
    """Interface for CSI-Addons volume operation builders.
    
    This abstract interface defines the contract for building CSI-Addons operations
    such as volume replication. Unlike VolumeBuilderI which handles volume lifecycle
    operations (create, delete, expand), VolumeAddonsBuilderI handles addon-specific
    operations that extend CSI functionality.
    
    Each addon type (replication, encryption, etc.) should implement this interface
    to provide a consistent builder pattern for addon operations.
    """

    @classmethod
    def from_parameters(cls, *args, **kwargs):
        """Creates an addon builder instance using the provided parameters.
        
        This method should parse and validate parameters specific to the addon operation,
        such as replication parameters (to be defined based on storage backend requirements).
        
        Args:
            *args: Positional arguments for initializing the builder.
            **kwargs: Keyword arguments for initializing the builder.
            
        Returns:
            VolumeAddonsBuilderI: An instance of the implementing addon builder class.
        """
        ...

    def execute(self, **kwargs):
        """Executes the addon operation.
        
        This method performs the actual addon operation (e.g., enable replication,
        promote volume, demote volume, etc.) using the validated parameters.
        
        Args:
            **kwargs: Additional runtime parameters for executing the operation.
            
        Returns:
            The result of the addon operation, specific to each implementation.
        """
        ...

    @classmethod
    def build(cls, *args, **kwargs):
        """
        Creates and executes an addon operation from provided arguments.
        
        Initializes a builder with the given parameters and invokes `execute`
        to perform the addon operation.
        
        Args:
            *args: Positional arguments for initializing the builder.
            **kwargs: Keyword arguments for initializing and executing the builder.
            
        Returns:
            The result of the addon operation.
        """
        builder = cls.from_parameters(*args, **kwargs)
        return builder.execute(**kwargs)


class CommonPropsMixin:

    @property
    def secondary_export_abs(self) -> str:
        """Return the absolute path for the root export."""
        return os.path.join("/", self.secondary_storage_path)

    def build_volume_name(self) -> str:
        """Build volume name using format csi:{namespace}:{name}:{id}"""
        volume_id = self.volume_id
        volume_name = f"csi-{volume_id}"

        if self.configuration.truncate_volume_name:
            volume_name = volume_name[:self.configuration.truncate_volume_name]

        return volume_name


class BaseAddonsBuilder(CommonPropsMixin, VolumeAddonsBuilderI):
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
