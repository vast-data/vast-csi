import json
from pathlib import Path
from vast_csi.filesystem_utils import hostcmd
from plumbum import cmd, ProcessExecutionError, FG
from plumbum.commands.processes import ProcessTimedOut
from vast_csi.logging import logger
from vast_csi.exceptions import Abort, LookupFieldError
from vast_csi.csi_types import ABORTED, INVALID_ARGUMENT
from vast_csi.serialization_utils import SerializationMixin
from vast_csi.configuration import Config

# Timeout for LUKS operations (in seconds)
# luksFormat with high pbkdf_memory can take a long time, but should not hang forever
LUKS_FORMAT_TIMEOUT = 600  # 10 minutes
LUKS_OPEN_TIMEOUT = 180     # 3 minutes


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

    def luks_device_exists(self) -> bool:
        """
        Check if the LUKS mapper device exists.
        Returns:
            bool: True if the mapper device exists, False otherwise.
        """
        return Path(self.luks_device_path).exists()


    def get_backing_block_device(self) -> str:
        """
        Extract the original backing device path for a given LUKS mapper device
        by traversing sysfs.
        
        Returns:
            str: The path to the original block device (e.g., '/dev/nvme1n2').

        Raises:
            RuntimeError: If the device cannot be determined.
        """
        # Check if the LUKS device exists
        luks_device_path = Path(self.luks_device_path)
        if not luks_device_path.exists():
            raise RuntimeError(f"LUKS device {self.luks_device_path} does not exist")
        
        try:
            # Resolve the symlink to get the actual device mapper name (dm-X)
            real_device = luks_device_path.resolve()
            dm_name = real_device.name  # This gives us dm-X
            
            # Look in sysfs for the slaves (backing devices)
            slaves_path = Path(f"/sys/block/{dm_name}/slaves")
            if not slaves_path.exists():
                raise RuntimeError(f"Sysfs slaves directory not found: {slaves_path}")
            
            # Get the backing devices
            slave_devices = list(slaves_path.iterdir())
            if not slave_devices:
                raise RuntimeError(f"No backing devices found in {slaves_path}")
            
            if len(slave_devices) > 1:
                logger.warning(f"Multiple backing devices found for {self.luks_device_path}: {[d.name for d in slave_devices]}")
            
            # Return the first (and typically only) backing device
            backing_device_name = slave_devices[0].name
            backing_device_path = f"/dev/{backing_device_name}"
            
            logger.debug(f"Found backing device {backing_device_path} for LUKS device {self.luks_device_path}")
            return backing_device_path
            
        except Exception as e:
            raise RuntimeError(f"Failed to determine backing device for {self.luks_device_path} via sysfs: {e}")

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
            # Build args explicitly (style consistent with luksFormat)
            cfg = self.encryption_config
            args = [
                "open",
            ]
            if cfg.get("perf-same_cpu_crypt", True):
                args += ["--perf-same_cpu_crypt"]
            if cfg.get("perf-submit_from_crypt_cpus", True):
                args += ["--perf-submit_from_crypt_cpus"]
            if cfg.get("perf-no_read_workqueue", True):
                args += ["--perf-no_read_workqueue"]
            if cfg.get("perf-no_write_workqueue", True):
                args += ["--perf-no_write_workqueue"]
            args += [
                device_path,
                self.luks_device_name,
            ]
            logger.info(f"LUKS open args: {args}")

            crypt_cmd = hostcmd.cryptsetup.get_executable(*args)
            echo_cmd = cmd.echo["-n", self.passphrase]
            # Add timeout protection to prevent hanging on OOM/killed processes
            (echo_cmd | crypt_cmd).run(timeout=LUKS_OPEN_TIMEOUT)
        except ProcessTimedOut:
            raise Abort(ABORTED, f"LUKS open timed out after {LUKS_OPEN_TIMEOUT}s for {device_path}")
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
            "--hash", self.encryption_config.get("hash", "sha256"),
            "--pbkdf-memory", self.encryption_config.get("pbkdf_memory", "65536"),
            "--batch-mode",
            "--key-file", "-",
            device_path,
        ]
        logger.info(f"LUKS encryption args: {args}")
        try:
            crypt_cmd = hostcmd.cryptsetup.get_executable(*args)
            echo_cmd = cmd.echo["-n", self.passphrase]
            # Add timeout protection to prevent hanging on OOM/killed processes
            (echo_cmd | crypt_cmd).run(timeout=LUKS_FORMAT_TIMEOUT)
        except ProcessTimedOut:
            raise Abort(ABORTED, f"LUKS format timed out after {LUKS_FORMAT_TIMEOUT}s for {device_path}. "
                        f"This may indicate insufficient memory for pbkdf_memory setting.")
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
