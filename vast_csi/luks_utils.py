import re
import json
from plumbum import local
from easypy.bunch import Bunch, bunchify
from easypy.collections import listify
from vast_csi.filesystem_utils import hostcmd, HostCommand
from plumbum import local, cmd, ProcessExecutionError
from vast_csi.logging import logger
from vast_csi.exceptions import Abort
from vast_csi.csi_types import NOT_FOUND

def luksDevicePath(volume_name):
    return f"/dev/mapper/{volume_name}"
def luksDeviceName(volume_id):
    return f"vast-csi-crypt-{volume_id}"
def isHostCryptPath(device, volume_id):
    return device == luksDevicePath(luksDeviceName(volume_id))

class LuksManager:
    def __init__(self, logger, vol_id=None, device_path=None, vol_context=None):
        self.vol_id = vol_id
        self.encryption_config = self._parse_encryption_config(vol_context or {})
        self.logger = logger
        self.device_path = device_path
        self.luks_device_name = luksDeviceName(vol_id)
        self.luks_device_path = luksDevicePath(self.luks_device_name)

    @staticmethod
    def _parse_encryption_config(vol_context):
        """
        Extracts host encryption params from the items dictionary.

        Args:
            items (dict): Dictionary containing volume context or parameters.

        Returns:
            dict: A dictionary of host encryption parameters without the prefix.
        """
        prefix = "host_encryption."
        return {
            key[len(prefix):]: value
            for key, value in vol_context.items()
            if key.startswith(prefix)
        }

    def init_host_encryption(self, passphrase: str) -> None:
        """
        Handle formatting and opening a LUKS device for a volume if not already done.

        Args:
            passphrase (str): Passphrase for encryption.
        """
        config = self.encryption_config
        luks_type = config.get("luks_type", "luks2")
        cipher = config.get("cipher", "aes-xts-plain64")
        key_size = config.get("key_size", "512")
        hash_algo = config.get("hash_algo", "sha256")
        pbkdf_mem = config.get("pbkdf_mem", "65536")

        # Check if LUKS device exists and active
        is_luks = self._is_luks_device()
        if not is_luks:
            # Format and open device
            self.logger.info(f"Formatting device {self.device_path} with LUKS")
            self._luks_format_device(
                passphrase=passphrase,
                luks_type=luks_type,
                cipher=cipher,
                key_size=key_size,
                hash_algo=hash_algo,
                pbkdf_mem=pbkdf_mem
            )
            self.logger.info(f"Opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
            self._luks_open_device(
                passphrase=passphrase
            )
            self.logger.info(f"Done opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
        elif not self._is_luks_active():
            # Device already LUKS encrypted, but not mapped because it isn't opened yet
            self.logger.info(f"Opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
            self._luks_open_device(
                passphrase=passphrase
            )
            self.logger.info(f"Done opening encrypted device {self.luks_device_path} as {self.luks_device_name}")
        else:
            # LUKS device exists and active
            self.logger.info(f"LUKS device already opened at {self.luks_device_path}")

    def _is_luks_device(self) -> bool:
        """
        Check if the given device is LUKS-encrypted or not.

        Args:
            None

        Returns:
            bool: True if the device is LUKS, False otherwise.
        """
        try:
            hostcmd.cryptsetup("isLuks", self.device_path)
            return True
        except ProcessExecutionError:
            return False

    def _is_luks_active(self) -> bool:
        """
        Check if a given LUKS mapping is currently active (opened).

        Args:
            None

        Returns:
            bool: True if the LUKS mapping is active, False otherwise.
        """
        try:
            output = hostcmd.cryptsetup("status", self.luks_device_name)
            return "LUKS2" in output.strip()
        except ProcessExecutionError:
            return False

    def fini_host_encryption(self) -> None:
        """
        Closes a mapped LUKS device, if open.

        This function delegates to _luks_close_device, which handles
        closing the LUKS device.
        """
        self._luks_close_device()

    def _luks_close_device(self) -> None:
        """
        Removes (closes) a mapped LUKS device.

        Args:
            None

        Raises:
            Abort: If cryptsetup command fails.
        """
        logger.info(f"Attempting to close LUKS device: {self.luks_device_name}")
        try:
            hostcmd.cryptsetup("luksClose", self.luks_device_name)
            self.logger.info(f"LUKS device {self.luks_device_name} closed successfully.")
        except ProcessExecutionError as e:
            self.logger.warning(f"Failed to close LUKS device {self.luks_device_name}: {e.stderr.strip() if e.stderr else str(e)}")

    def _luks_open_device(self, passphrase: str) -> None:
        """
        Open a LUKS-encrypted device and map it to a specified device name.

        Args:
            passphrase (str): Passphrase to unlock the LUKS device.

        Raises:
            Abort: If cryptsetup fails to open the device.
        """
        try:
            hostcmd = HostCommand("cryptsetup")
            crypt_cmd = hostcmd.get_executable("open", self.device_path, self.luks_device_name)
            echo_cmd = local["echo"]["-n", passphrase]
            retcode, stdout, stderr = (echo_cmd | crypt_cmd).run(retcode=None)

        except ProcessExecutionError as e:
            raise Abort(NOT_FOUND, f"Failed to open LUKS device {device_path}: {e.stderr.strip() if e.stderr else str(e)}")

    def _luks_format_device(self, passphrase: str, luks_type: str, cipher: str,
                           key_size: str, hash_algo: str,
                           pbkdf_mem: str) -> None:
        """
        Format a block device with LUKS encryption using cryptsetup on the Docker host.

        Args:
            passphrase (str): Passphrase for LUKS encryption.
            luks_type (str): LUKS format type (e.g., luks1, luks2).
            cipher (str): Cipher algorithm to use (e.g., aes-xts-plain64).
            key_size (str): Key size in bits (e.g., 512).
            hash_algo (str): Hash algorithm (e.g., sha256).
            pbkdf_mem (str): PBKDF memory in KB (e.g., 65536).

        Raises:
            Abort: If cryptsetup fails.
        """
        try:
            hostcmd = HostCommand("cryptsetup")
            crypt_cmd = hostcmd.get_executable(
                "luksFormat",
                "--type", luks_type,
                "--cipher", cipher,
                "--key-size", key_size,
                "--hash", hash_algo,
                "--pbkdf-memory", pbkdf_mem,
                "--batch-mode", self.device_path,
            )
            echo_cmd = local["echo"]["-n", passphrase]
            retcode, stdout, stderr = (echo_cmd | crypt_cmd).run(retcode=None)

        except ProcessExecutionError as e:
            raise Abort(NOT_FOUND, f"LUKS format failed for {self.device_path}: {e.stderr.strip() if e.stderr else str(e)}")

    def luks_resize_device(self, passphrase: str) -> bool:
        """
        Resize the LUKS-encrypted device and the filesystem inside it.

        Args:
            passphrase (str): Passphrase for LUKS encryption.

        Returns:
            bool: True if the device and filesystem were resized successfully, False otherwise.
        """
        if not self._is_luks_device():
            self.logger.info(f"Device {self.luks_device_path} is not a LUKS-encrypted device.")
            return False

        try:
            hostcmd = HostCommand("cryptsetup")
            crypt_cmd = hostcmd.get_executable(
                "resize",
                self.luks_device_path,
            )
            echo_cmd = local["echo"]["-n", passphrase]
            retcode, stdout, stderr = (echo_cmd | crypt_cmd).run(retcode=None)
            self.logger.info(f"Device {self.luks_device_path} resized successfully")
            return True

        except ProcessExecutionError as e:
            self.logger.error(f"Error resizing LUKS device {self.luks_device_path}: {e}")
            return False
