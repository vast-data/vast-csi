import json
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
    encryption_config = {}
    if volume_context:
        host_encryption = volume_context.get("host_encryption")
        if host_encryption:
            encryption_config = json.loads(host_encryption)
    return LuksManager.create(
        config=config,
        volume_id=volume_id,
        passphrase=passphrase,
        encryption_config=encryption_config,
        cluster_name=cluster_name,
    )

class LuksManager(SerializationMixin):
    def __init__(self, volume_id: str, passphrase: str = None, encryption_config: dict = None):
        self.volume_id = volume_id
        self.passphrase = passphrase
        self.encryption_config = encryption_config
        self.luks_device_name = f"vast-csi-crypt-{volume_id}"
        self.luks_device_path = f"/dev/mapper/{self.luks_device_name}"


    @classmethod
    def create(cls, config, volume_id, passphrase, encryption_config, cluster_name):
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
            encryption_config (dict, optional): Encryption configuration parameters for LUKS.
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
            encryption_config=encryption_config,

        )

    def dump_data(self) -> object:
        return {
            "volume_id": self.volume_id,
            "passphrase": self.passphrase,
            "encryption_config": self.encryption_config,
        }


    @staticmethod
    def load_data(data_fields: dict) -> "LuksManager":
        """
        Reconstruct an object from deserialized data fields.
        Args:
            data_fields: The result of unpickling the stored internal state.
        Returns:
            An instance of the LuksManager class.
        """
        return LuksManager(**data_fields)

    def requires_encryption(self) -> bool:
        """Check if LUKS encryption is active (i.e., passphrase is supplied)."""
        if self.encryption_config and not self.passphrase:
            raise Abort(INVALID_ARGUMENT, "Encryption config is present but passphrase is missing.")
        return bool(self.passphrase)

    def _require_passphrase(self):
        if not self.passphrase:
            raise Abort(INVALID_ARGUMENT, "Passphrase must be provided for LUKS operations")

    def init_host_encryption(self, device_path: str) -> str:
        """
        Prepare and activate LUKS encryption on the specified device.

        - If the device is not yet encrypted, it will be formatted with LUKS and mapped.
        - If already encrypted but not active, it will be mapped.
        - If already mapped, no action is taken.

        Returns:
            The path to the active LUKS device (e.g., /dev/mapper/csi-<volume>).
        """
        if not self._is_luks_device(device_path=device_path):
            logger.info(f"Initializing LUKS encryption on device: {device_path}")
            self._luks_format_device(device_path=device_path)

            logger.info(f"Mapping LUKS device: {self.luks_device_path}")
            self._luks_open_device(device_path=device_path)
            logger.info(f"LUKS device mapped successfully: {self.luks_device_path}")

        elif not self._is_luks_active():
            logger.info(f"Detected encrypted but inactive LUKS device: {self.luks_device_path}")
            logger.info(f"Mapping existing LUKS device: {self.luks_device_path}")
            self._luks_open_device(device_path=device_path)
            logger.info(f"LUKS device mapped successfully: {self.luks_device_path}")

        else:
            logger.info(f"LUKS device already active: {self.luks_device_path}")

        return self.luks_device_path

    def _is_luks_device(self, device_path: str) -> bool:
        """Check if the raw device is LUKS-encrypted."""
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
            logger.warning(f"Failed to close LUKS device {self.luks_device_name}: {e.stderr}")
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
            raise Abort(ABORTED, f"Failed to open LUKS device {device_path}: {e.stderr}")

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
        logger.info(f"LUKS encryption args: {args}")
        try:
            crypt_cmd = hostcmd.cryptsetup.get_executable(*args)
            echo_cmd = cmd.echo["-n", self.passphrase]
            (echo_cmd | crypt_cmd) & FG
        except ProcessExecutionError as e:
            raise Abort(ABORTED, f"LUKS format failed for {device_path}: {e.stderr}")

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
            logger.error(f"Error resizing LUKS device {self.luks_device_path}: {e.stderr}")
            return False
