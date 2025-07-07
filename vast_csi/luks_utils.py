from pathlib import Path
from vast_csi.filesystem_utils import hostcmd
from plumbum import cmd, ProcessExecutionError, FG
from vast_csi.logging import logger
from vast_csi.exceptions import Abort, LookupFieldError
from vast_csi.csi_types import ABORTED, INVALID_ARGUMENT
from vast_csi.serialization_utils import SerializationMixin
from vast_csi.configuration import Config


def get_luks_manager(
        volume_id: str,
        passphrase: str = None,
        volume_context: dict = None,
        cluster_name: str = None,
) -> "LuksManager":
    """Factory function to create a LuksManager instance."""
    config = Config()
    return LuksManager.create(
        config=config,
        volume_id=volume_id,
        passphrase=passphrase,
        volume_context=volume_context,
        cluster_name=cluster_name,
    )


class LuksManager(SerializationMixin):
    def __init__(self, volume_id: str, passphrase: str = None, volume_context: dict = None):
        self.volume_id = volume_id
        self.passphrase = passphrase
        self.raw_volume_context = volume_context or {}
        self.encryption_config = self._parse_encryption_config(self.raw_volume_context)
        self.luks_device_name = f"vast-csi-crypt-{volume_id}"
        self.luks_device_path = f"/dev/mapper/{self.luks_device_name}"


    @classmethod
    def create(cls, config, volume_id, passphrase, volume_context, cluster_name):
        """
        Creates a LuksManager instance, resolving the encryption passphrase from
        arguments or secret-based configuration.

        If `cluster_name` is provided, the passphrase is loaded from a multi-cluster YAML config.
        If not, and no passphrase is given, it falls back to the deprecated global secret.

        Args:
            config (Config): The configuration object containing secret paths and settings.
            volume_id (str): The unique identifier for the volume to encrypt.
            passphrase (str, optional): The passphrase used for LUKS encryption. If not provided,
                it will be resolved from secret configuration.
            volume_context (dict, optional): Volume context fields, typically from the StorageClass.
            cluster_name (str, optional): The cluster name to use when resolving secrets
                from a multi-cluster configuration.

        Behavior:
            The passphrase is resolved based on the following logic:

            1. **StorageClass Secret (Recommended)**:
                If `cluster_name` is not provided and `passphrase` is explicitly passed,
                it is used directly. This is the preferred method for secure encryption.

            2. **Multi-Cluster Secret**:
                If `cluster_name` is provided, the passphrase is read from a YAML config mounted
                at `/opt/vms-auth/clusters`, where each top-level key is a cluster name. For example:

                ```yaml
                cluster1:
                  passphrase: my-secret-key
                cluster2:
                  passphrase: another-secret
                ```

            3. **Global Secret (Deprecated)**:
                If neither `cluster_name` nor a direct `passphrase` is provided,
                the passphrase is loaded from the global secret (e.g., `/opt/vms-auth/passphrase`).
                This method is discouraged and retained for backward compatibility.

        Returns:
            LuksManager: A configured instance ready to manage LUKS operations for the specified volume.

        Raises:
            LookupFieldError: If a required value like the passphrase is missing from the expected source.
        """
        if cluster_name:
            if not (cluster_auth_config := config.cluster_credentials.get(cluster_name)):
                raise LookupFieldError(field="cluster_name", tip="Make sure cluster name is present in secret.")
            passphrase = cluster_auth_config.get("passphrase")
        else:
            # The presence of the passphrase in the arguments already indicates
            # that we have a StorageClass scope secret at this point.
            # In other words, it's not a globally mounted secret. Other secret fields will be validated below.
            is_global = not bool(passphrase)
            if config.vms_credentials_store.exists() and is_global:
                passphrase = config.host_encryption_passphrase

        return cls(
            volume_id=volume_id,
            passphrase=passphrase,
            volume_context=volume_context,

        )

    def dump_data(self) -> object:
        return self.volume_id, self.passphrase, self.raw_volume_context

    @staticmethod
    def load_data(data_fields: object) -> "LuksManager":
        """
        Reconstruct an object from deserialized data fields.
        Args:
            data_fields: The result of unpickling the stored internal state.
        Returns:
            An instance of the LuksManager class.
        """
        volume_id, passphrase, volume_context = data_fields
        return get_luks_manager(volume_id=volume_id, passphrase=passphrase, volume_context=volume_context)


    @staticmethod
    def _parse_encryption_config(vol_context: dict) -> dict:
        prefix = "host_encryption."
        return {
            key[len(prefix):]: value
            for key, value in vol_context.items()
            if key.startswith(prefix)
        }

    def requires_encryption(self) -> bool:
        """Check if LUKS encryption is active (i.e., passphrase is supplied)."""
        if self.encryption_config and not self.passphrase:
            raise Abort(INVALID_ARGUMENT, "Encryption config is present but passphrase is missing.")
        return bool(self.passphrase)

    def _require_passphrase(self):
        if not self.passphrase:
            raise Abort(INVALID_ARGUMENT, "Passphrase must be provided for LUKS operations")


    def init_host_encryption(self, device_path: str) -> None:
        """
        Handle formatting and opening a LUKS device for a volume if not already done.
        """

        # Check if LUKS device exists and active
        is_luks = self._is_luks_device(device_path=device_path)
        if not is_luks:
            # Format and open device
            logger.info(f"Formatting device {device_path} with LUKS")
            self._luks_format_device(
               device_path=device_path,
            )
            logger.info(f"Opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
            self._luks_open_device(device_path=device_path)
            logger.info(f"Done opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
        elif not self._is_luks_active():
            # Device already LUKS encrypted, but not mapped because it isn't opened yet
            logger.info(f"Opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
            self._luks_open_device(device_path=device_path)
            logger.info(f"Done opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
        else:
            # LUKS device exists and active
            logger.info(f"LUKS device already opened at {self.luks_device_path}")

    def _is_luks_device(self, device_path: str) -> bool:
        """Check if the raw device is LUKS-encrypted."""
        if not Path(device_path).exists():
            return False
        try:
            hostcmd.cryptsetup("isLuks", device_path)
            return True
        except ProcessExecutionError:
            return False

    def _is_luks_active(self) -> bool:
        """
        Check if a given LUKS mapping is currently active (opened).
        Returns:
            bool: True if the LUKS mapping is active, False otherwise.
        """
        try:
            output = hostcmd.cryptsetup("status", self.luks_device_name)
            return "LUKS2" in output.strip()
        except ProcessExecutionError:
            return False

    def luks_close_device(self) -> bool:
        """
        Safely close the LUKS device if it exists and is mapped.
        Returns:
          bool: True if the device was closed, False if no mapped device was found or it failed to close.
        """
        if not Path(self.luks_device_path).exists():
            logger.debug(f"No mapped LUKS device found at {self.luks_device_path}.")
            return False

        try:
            hostcmd.cryptsetup("luksClose", self.luks_device_name)
            logger.info(f"LUKS device {self.luks_device_name} closed successfully.")
            return True
        except ProcessExecutionError as e:
            logger.warning(f"Failed to close LUKS device {self.luks_device_name}: {e}")
            return False

    def _luks_open_device(self, device_path: str) -> None:
        """Run `cryptsetup open` with stdin passphrase."""
        self._require_passphrase()

        try:
            crypt_cmd = hostcmd.cryptsetup.get_executable(
                "open", device_path, self.luks_device_name
            )
            echo_cmd = cmd.echo["-n", self.passphrase]
            (echo_cmd | crypt_cmd) & FG
        except ProcessExecutionError as e:
            raise Abort(ABORTED, f"Failed to open LUKS device {device_path}: {e}")

    def _luks_format_device(self, device_path: str) -> None:
        """Run `cryptsetup luksFormat` with stdin passphrase."""
        self._require_passphrase()

        args = [
            "luksFormat",
            "--type", self.encryption_config.get("luks_type", "luks2"),
            "--cipher", self.encryption_config.get("cipher", "aes-xts-plain64"),
            "--key-size", self.encryption_config.get("key_size", "512"),
            "--hash", self.encryption_config.get("hash_algo", "sha256"),
            "--pbkdf-memory", self.encryption_config.get("pbkdf_mem", "65536"),
            "--batch-mode",
            "--key-file", "-",
            device_path,
        ]
        try:
            crypt_cmd = hostcmd.cryptsetup.get_executable(*args)
            echo_cmd = cmd.echo["-n", self.passphrase]
            (echo_cmd | crypt_cmd) & FG
        except ProcessExecutionError as e:
            raise Abort(ABORTED, f"LUKS format failed for {device_path}: {e}")

    def luks_resize_device(self, device_path: str) -> bool:
        """
        Resize the LUKS-encrypted device.

        This adjusts the LUKS container size after the underlying block device has grown.
        The decrypted /dev/mapper path remains the same, but the LUKS metadata must be adjusted.

        Args:
            device_path (str): The original encrypted block device path (e.g., /dev/nvme0n1)

        Returns:
            bool: True if resized successfully, False otherwise.
        """
        self._require_passphrase()

        if not self._is_luks_device(device_path):
            logger.info(f"Device {device_path} is not a LUKS-encrypted device.")
            return False

        try:
            crypt_cmd = hostcmd.cryptsetup.get_executable("resize", self.luks_device_path)
            echo_cmd = cmd.echo["-n", self.passphrase]
            (echo_cmd | crypt_cmd) & FG
            logger.info(f"LUKS device {self.luks_device_path} resized successfully.")
            return True
        except ProcessExecutionError as e:
            logger.error(f"Error resizing LUKS device {self.luks_device_path}: {e}")
            return False
