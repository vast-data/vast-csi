import re
import json
from itertools import chain

from easypy.caching import cached_property
from easypy.collections import iterable, listify

from vast_csi.csi_types import AccessModeType as access_modes
from vast_csi.exceptions import CapValidationError

SUPPORTED_FS_TYPES = ["ext4", "ext3", "xfs"]
DEFAULT_FS_TYPE = "ext4"


class ServiceCapabilities:
    """
    ServiceCapabilities manages the validation and support of block and mount volume capabilities,
    including support for multi-node access modes.
    Attributes:
        support_block (bool): Whether block access type is supported.
        support_filesystem (bool): Whether filesystem access type is supported.
        can_many_rwx (bool): Whether multi-node read-write access modes are supported.
        SUPPORTED_ACCESS (tuple): Supported access modes based on the service's configuration.
    """

    def __init__(self, support_block: bool, support_filesystem: bool, can_many_rwx: bool):
        """
        Initializes the ServiceCapabilities object.
        Args:
            support_block (bool): Whether block access type is supported.
            support_filesystem (bool): Whether mount access type is supported.
            can_many_rwx (bool): Whether multi-node read-write access modes are supported.
        """
        self.support_block = support_block
        self.support_filesystem = support_filesystem
        self.can_many_rwx = can_many_rwx

        # Set supported access modes
        self.SUPPORTED_ACCESS = Capability.SINGLE_ACCESS_MODES
        if self.can_many_rwx:
            self.SUPPORTED_ACCESS += Capability.MULTI_ACCESS_MODES

    def validate(self, capabilities: "Capabilities"):
        """
        Validates the given Capabilities object based on the service's supported capabilities.
        Args:
            capabilities (Capabilities): The capabilities to validate.
        """
        if not self.support_block and capabilities.is_block:
            raise CapValidationError(cap=capabilities, reason="block access type is not supported")

        elif not self.support_filesystem and capabilities.is_filesystem:
            raise CapValidationError(cap=capabilities, reason="filesystem access type is not supported")

        elif capabilities.fs_type and capabilities.fs_type not in SUPPORTED_FS_TYPES:
            raise CapValidationError(
                cap=capabilities, reason=f"unsupported file system type: {capabilities.fs_type}"
            )
        if capabilities.multi_mode and not self.can_many_rwx:
            raise CapValidationError(
                cap=capabilities, reason="multi-node access mode is not supported"
            )

    def make_and_validate(self, capabilities, volume_context=None, publish_context=None):
        """
        Creates a Capabilities object from a list of capabilities and validates it.
        Args:
            capabilities (list): A list of Capability objects or dictionaries.
        Returns:
            Capabilities: The validated Capabilities object.
        """
        capabilities = Capabilities(
            capabilities=listify(capabilities), volume_context=volume_context, publish_context=publish_context
        )
        self.validate(capabilities)
        return capabilities


class Capabilities:
    """
    Represents a collection of Capability objects. Provides methods to check and retrieve various
    properties, such as access modes and filesystem types.
    """

    def __init__(self, capabilities, volume_context=None, publish_context=None):
        """
        Initializes the Capabilities object with a list of Capability objects.
        Args:
            capabilities (list): A list of Capability objects or dictionaries to initialize.
            volume_context (dict): The volume context to use for validation.
        """
        self.capabilities = [
            c if isinstance(c, Capability) else Capability(c, volume_context, publish_context) for c in capabilities
        ]

    def __str__(self):
        """Returns a JSON string representation of the capabilities."""
        return json.dumps(self.json, separators=(",", ":"))

    __repr__ = __str__

    def __iter__(self):
        """
        Iterator method for the Capabilities object, allowing iteration over the capabilities.
        """
        return iter(self.capabilities)

    @cached_property
    def multi_mode(self):
        """
        Cached property that checks if any of the capabilities support multi-node access.
        Returns:
            bool: True if any capability supports multi-node access, otherwise False.
        """
        return any(c.multi_mode for c in self)

    @cached_property
    def ro_mode(self):
        """
        Cached property that checks if all capabilities are in read-only mode.
        Returns:
            bool: True if all capabilities are read-only, otherwise False.
        """
        return all(c.ro_mode for c in self)

    @cached_property
    def rw_mode(self):
        """
        Cached property that checks if any capability is in read-write mode.
        Returns:
            bool: True if any capability is in read-write mode, otherwise False.
        """
        return not self.ro_mode

    @cached_property
    def is_readonly(self):
        """
        True when any capability requires kernel-level read-only enforcement via
        blockdev --setro (covers both raw block and filesystem volumes).
        """
        return any(c.is_readonly for c in self)

    @cached_property
    def is_block(self):
        """
        Cached property that checks if any of the capabilities are block-based.
        Returns:
            bool: True if any capability is block-based, otherwise False.
        """
        return any(c.is_block for c in self)

    @cached_property
    def is_filesystem(self):
        """
        Cached property that checks if any of the capabilities are filesystem-based.
        Returns:
            bool: True if any capability is mount-based, otherwise False.
        """
        return any(c.is_filesystem for c in self)

    @cached_property
    def fs_type(self):
        """
        Cached property that retrieves the filesystem type of the first capability (if applicable).
        Returns:
            str: Filesystem type (e.g., "ext4").
        """
        return next((c.fs_type for c in self), DEFAULT_FS_TYPE)

    @cached_property
    def access_mode(self):
        """
        Cached property that retrieves the access mode of the first capability.
        Returns:
            str: The access mode (e.g., "SINGLE_NODE_WRITER").
        """
        return next(c.access_mode for c in self)

    @cached_property
    def mount_flags(self):
        """
        Cached property that retrieves the mount flags of the first capability.
        Returns:
            str: The mount flags (if applicable), otherwise an empty string.
        """
        return next((c.mount_flags for c in self if c.mount_flags), [])


    @cached_property
    def mount_flags_str(self):
        """
        Returns the mount flags as a string.
        Returns:
            str: The mount flags as a string.
        """
        return ",".join(self.mount_flags)

    @cached_property
    def json(self):
        """
        Returns a dictionary representation of the capabilities as JSON.
        Returns:
            dict: A dictionary containing attributes like `is_block`, `is_filesystem`, `access_mode`,
                  `fs_type`, and `mount_flags`.
        """
        res = {
            "is_block": self.is_block,
            "is_filesystem": self.is_filesystem,
            "access_mode": self.access_mode,
            "fs_type": self.fs_type,
            "mount_flags": self.mount_flags_str,
        }
        return res


class Capability:
    """
    Represents a single volume capability, including access type, access mode, filesystem type,
    and mount flags. Also supports equality comparisons.
    """

    SINGLE_NODE_WRITER = access_modes.SINGLE_NODE_WRITER
    SINGLE_NODE_READER_ONLY = access_modes.SINGLE_NODE_READER_ONLY
    MULTI_NODE_READER_ONLY = access_modes.MULTI_NODE_READER_ONLY
    MULTI_NODE_SINGLE_WRITER = access_modes.MULTI_NODE_SINGLE_WRITER
    MULTI_NODE_MULTI_WRITER = access_modes.MULTI_NODE_MULTI_WRITER
    SINGLE_NODE_SINGLE_WRITER = access_modes.SINGLE_NODE_SINGLE_WRITER

    SINGLE_ACCESS_MODES = (SINGLE_NODE_WRITER, SINGLE_NODE_READER_ONLY, SINGLE_NODE_SINGLE_WRITER)
    MULTI_ACCESS_MODES = (
        MULTI_NODE_READER_ONLY,
        MULTI_NODE_SINGLE_WRITER,
        MULTI_NODE_MULTI_WRITER,
    )
    RO_ACCESS_MODES = (SINGLE_NODE_READER_ONLY, MULTI_NODE_READER_ONLY)

    def __init__(self, capability, volume_context=None, publish_context=None):
        """
        Initializes the Capability object with the provided capability.
        Args:
            capability (CapabilityProto): A CapabilityProto object, which must have fields for
                                          `block` or `mount`.
            volume_context (dict): The volume context to use for validation.
        """
        volume_context = volume_context or {}
        publish_context = publish_context or {}
        self.is_block = capability.HasField("block")
        self.is_filesystem = capability.HasField("mount")
        self.access_mode = capability.access_mode.mode
        mount_flags = capability.mount.mount_flags
        if iterable(mount_flags):
            mount_flags = ",".join(mount_flags)

        context_mount_flags = volume_context.get("mount_options", publish_context.get("mount_options", "")).split()
        capability_mount_flags = re.sub(r"[\[\]]", "", mount_flags).replace(",", " ").split()
        # Common aggregated mount flags.
        self.mount_flags = sorted(
            {op.strip() for op in chain.from_iterable([context_mount_flags, capability_mount_flags]) if op}
        )
        self.fs_type = ""
        if self.is_filesystem:
            self.fs_type = capability.mount.fs_type or DEFAULT_FS_TYPE
        self.ro_mode = self.access_mode in self.RO_ACCESS_MODES
        self.multi_mode = self.access_mode not in self.SINGLE_ACCESS_MODES

    @property
    def is_readonly(self):
        """True when this capability requires read-only enforcement via blockdev --setro.

        Covers both raw block and filesystem volumes: any volume whose access mode or
        mount flags indicate read-only access should have the kernel-level block device
        flag set, regardless of volume mode.
        """
        return self.ro_mode or "ro" in self.mount_flags

    def __eq__(self, other):
        """Compares two Capability objects for equality."""
        if not isinstance(other, Capability):
            other = Capability(other)

        res = (
            self.is_block == other.is_block
            and self.access_mode == other.access_mode
            and self.fs_type == other.fs_type
            and self.mount_flags == other.mount_flags
        )
        return res

    def json(self):
        """Returns a dictionary representation of the capability."""
        return {
            "is_block": self.is_block,
            "is_filesystem": self.is_filesystem,
            "access_mode": self.access_mode,
            "fs_type": self.fs_type,
            "mount_flags": self.mount_flags,
        }
