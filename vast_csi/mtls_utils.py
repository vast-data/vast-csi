"""mTLS credentials for NFS mount authentication using kernel keyring."""

import subprocess
import re
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from keyctl import KeyctlWrapper

from easypy.caching import timecache
from easypy.units import MINUTE
from vast_csi.logging import logger
from vast_csi.exceptions import LookupFieldError, XprtsecValidationError
from vast_csi.serialization_utils import SerializationMixin
from vast_csi.configuration import Config
from vast_csi.utils import is_ver_nfs4_present


# Key names for the .nfs: keyring (per NFS documentation)
NFS_KEYRING_NAME = ".nfs:"

# Per-volume key prefixes for mTLS credentials
MTLS_CERT_KEY_PREFIX = "vast-client-cert-"
MTLS_PRIVKEY_KEY_PREFIX = "vast-client-privkey-"

# Valid xprtsec values for NFS transport security
VALID_XPRTSEC_VALUES = ("", "tls", "mtls")


def get_xprtsec_from_mount_options(mount_options: str) -> str:
    """
    Extract and validate xprtsec value from mount options.
    
    Args:
        mount_options: Comma-separated mount options string or list
        
    Returns:
        xprtsec value ("tls", "mtls") or empty string if not specified
        
    Raises:
        XprtsecValidationError: If xprtsec value is not "", "tls", or "mtls"
    """
    if not mount_options:
        return ""
    # Handle both comma-separated string and list inputs
    if isinstance(mount_options, str):
        options = mount_options.split(",")
    else:
        options = list(mount_options) if not isinstance(mount_options, list) else mount_options
    for opt in options:
        name, _, value = opt.partition("=")
        if name == "xprtsec":
            if value not in VALID_XPRTSEC_VALUES:
                raise XprtsecValidationError(
                    f"Invalid xprtsec value: {value!r}. Must be one of {VALID_XPRTSEC_VALUES}"
                )
            return value
    return ""


@timecache(expiration=MINUTE * 5)
def get_nfs_keyring_id():
    """
    Find the .nfs: keyring ID created by the NFS subsystem (tlshd).
    
    The .nfs: keyring is created by tlshd when it starts. This function
    finds that keyring and links it to the session keyring for access.
    
    Returns:
        int: The keyring ID of the .nfs: keyring
        
    Raises:
        RuntimeError: If .nfs: keyring is not found (tlshd may not be running)
    """
    # Read /proc/keys to find the .nfs: keyring
    try:
        with open("/proc/keys", "r") as f:
            keys_content = f.read()
    except IOError as e:
        raise RuntimeError(f"Failed to read /proc/keys: {e}")
    
    # Parse /proc/keys to find .nfs: keyring
    # Format: "0a1b2c3d I--Q---     1 perm 1f3f0000     0     0 keyring   .nfs: 1"
    for line in keys_content.splitlines():
        if NFS_KEYRING_NAME in line and "keyring" in line:
            # Extract the key ID (first field, hex without 0x prefix)
            match = re.match(r'^([0-9a-f]+)\s+', line)
            if match:
                keyring_id = int(match.group(1), 16)
                logger.debug(f"Found {NFS_KEYRING_NAME} keyring: {hex(keyring_id)}")
                
                # Link the .nfs: keyring to session keyring for persistence
                try:
                    subprocess.run(
                        ["keyctl", "link", hex(keyring_id), "@s"],
                        capture_output=True,
                        check=True,
                    )
                    logger.debug(f"Linked {NFS_KEYRING_NAME} keyring to session keyring")
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to link keyring to session: {e}")
                
                return keyring_id
    
    raise RuntimeError(
        f"Could not find {NFS_KEYRING_NAME} keyring in /proc/keys. "
        f"Ensure tlshd service is running: systemctl start tlshd"
    )


def pem_to_der(pem_content: str) -> bytes:
    """Convert PEM format certificate/key to DER format."""

    pem_bytes = pem_content.encode()

    # Try to load as certificate
    if "BEGIN CERTIFICATE" in pem_content:
        cert = x509.load_pem_x509_certificate(pem_bytes, default_backend())
        return cert.public_bytes(serialization.Encoding.DER)

    # Try to load as private key
    elif "BEGIN PRIVATE KEY" in pem_content or "BEGIN RSA PRIVATE KEY" in pem_content:
        private_key = serialization.load_pem_private_key(
            pem_bytes, password=None, backend=default_backend()
        )
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

    else:
        raise ValueError(
            "Invalid PEM content - must contain certificate or private key"
        )


def load_pem_to_keyring(pem_content: str, key_name: str) -> int:
    """
    Load PEM content (certificate or private key) into the .nfs: kernel keyring.
    
    This function loads credentials into the official NFS keyring (.nfs:) that is
    created by tlshd. The kernel NFS client looks for certs in this keyring when
    using cert_serial/privkey_serial mount options.
    
    Reuses existing key if already loaded.
    To refresh credentials, unstage and restage the volume (delete and recreate the pod).

    Args:
        pem_content: PEM formatted certificate or private key
        key_name: Name for the key in the keyring (e.g., "nfs-client-cert")

    Returns:
        int: Key serial ID for use in mount options
    """
    if key_serial := search_in_keyring(key_name):
        logger.debug(
            f"Reusing existing key '{key_name}' from keyring: serial={key_serial}"
        )
        return key_serial

    keyring_id = get_nfs_keyring_id()

    # Convert PEM to DER (binary format)
    der_content = pem_to_der(pem_content)

    # Add binary DER data to keyring by piping directly to keyctl padd
    #
    # NOTE: We cannot use KeyctlWrapper.add_key() directly because:
    # - DER certificates/keys are binary data (bytes)
    # - KeyctlWrapper._system() uses text=True in subprocess.Popen
    # - text=True tries to decode binary data as UTF-8, which fails
    proc = subprocess.Popen(
        ["keyctl", "padd", "user", key_name, hex(keyring_id)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate(input=der_content)

    if proc.returncode != 0:
        raise RuntimeError(
            f"Failed to add key '{key_name}' to {NFS_KEYRING_NAME} keyring: {stderr.decode('utf-8', errors='replace')}"
        )

    key_serial = int(stdout.decode().strip())

    # Set permissions to allow NFS client and tlshd to access (0x3f3f0000)
    keyctl = KeyctlWrapper(keyring=str(keyring_id))
    keyctl._system(["keyctl", "setperm", str(key_serial), "0x3f3f0000"])

    logger.info(
        f"Loaded '{key_name}' into {NFS_KEYRING_NAME} keyring: serial={key_serial}"
    )
    return key_serial


def search_in_keyring(key_name: str) -> Optional[int]:
    """
    Search for a key in the .nfs: kernel keyring by name.
    
    Args:
        key_name: Name of the key to search for
        
    Returns:
        Key serial number if found, None otherwise
    """
    try:
        keyring_id = get_nfs_keyring_id()
    except RuntimeError:
        # .nfs: keyring doesn't exist
        return None

    try:
        # Search for key serial without reading its data
        proc = subprocess.run(
            ["keyctl", "search", hex(keyring_id), "user", key_name],
            capture_output=True,
            check=True,
            text=True,
        )
        key_serial = int(proc.stdout.strip())
        logger.debug(f"Found existing key '{key_name}' in {NFS_KEYRING_NAME} keyring: serial={key_serial}")
        return key_serial
    except subprocess.CalledProcessError:
        # Key doesn't exist
        logger.debug(f"Key '{key_name}' not found in {NFS_KEYRING_NAME} keyring")
        return None


def delete_from_keyring(key_name: str) -> None:
    """
    Delete a key from the .nfs: kernel keyring by name.
    Idempotent: succeeds silently if the key doesn't exist.

    Args:
        key_name: Name of the key to delete from the keyring
    """
    key_serial = search_in_keyring(key_name)

    if key_serial is None:
        logger.debug(f"Key '{key_name}' not found in keyring or already deleted")
        return

    try:
        subprocess.run(
            ["keyctl", "unlink", str(key_serial)],
            capture_output=True,
            check=True,
        )
        logger.info(f"Deleted '{key_name}' from {NFS_KEYRING_NAME} keyring")
    except subprocess.CalledProcessError as e:
        logger.debug(f"Key '{key_name}' was already deleted or unlink failed: {e}")


def load_mtls_credentials(cert_pem: str, privkey_pem: str, volume_id: str) -> tuple:
    """
    Load mTLS certificate and private key into the .nfs: kernel keyring.

    Args:
        cert_pem: PEM formatted client certificate
        privkey_pem: PEM formatted private key
        volume_id: Volume ID for unique key naming

    Returns:
        tuple: (cert_serial, privkey_serial) for use in mount options
    """
    cert_key_name = f"{MTLS_CERT_KEY_PREFIX}{volume_id}"
    privkey_key_name = f"{MTLS_PRIVKEY_KEY_PREFIX}{volume_id}"
    
    cert_serial = load_pem_to_keyring(cert_pem, cert_key_name)
    privkey_serial = load_pem_to_keyring(privkey_pem, privkey_key_name)
    return cert_serial, privkey_serial


def delete_mtls_credentials(volume_id: str) -> None:
    """
    Delete mTLS certificate and private key from the .nfs: kernel keyring.

    Args:
        volume_id: Volume ID for unique key naming
    """
    cert_key_name = f"{MTLS_CERT_KEY_PREFIX}{volume_id}"
    privkey_key_name = f"{MTLS_PRIVKEY_KEY_PREFIX}{volume_id}"
    
    delete_from_keyring(cert_key_name)
    delete_from_keyring(privkey_key_name)


def validate_xprtsec_view_policy(view_policy_obj, xprtsec: str, is_nfs4: bool = False) -> None:
    """
    Validate that view policy TLS settings match the requested xprtsec mode.

    Required view policy settings:
    - xprtsec=""     : nfs_enforce_tls=False, nfs_enforce_mtls=False
    - xprtsec="tls"  : nfs_enforce_tls=True, nfs_enforce_mtls=False
    - xprtsec="mtls" : nfs_enforce_tls=True, nfs_enforce_mtls=True

    For NFSv3 only (is_nfs4=False):
    - xprtsec="tls"/"mtls" also requires nfs_enforce_tls_relaxed=True
      (NFSv3 uses separate NLM protocol for locking which needs relaxed mode)

    For NFSv4 (is_nfs4=True):
    - nfs_enforce_tls_relaxed is ignored (NFSv4 includes locking in main protocol)

    Raises:
        XprtsecValidationError: If the view policy settings don't match xprtsec requirements
    """
    policy_name = getattr(view_policy_obj, 'name', 'unknown')
    enforce_tls = getattr(view_policy_obj, 'nfs_enforce_tls', False)
    enforce_tls_relaxed = getattr(view_policy_obj, 'nfs_enforce_tls_relaxed', False)
    enforce_mtls = getattr(view_policy_obj, 'nfs_enforce_mtls', False)

    # Plain NFS: policy must not enforce any TLS
    if not xprtsec:
        if enforce_tls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_tls=True, "
                f"but xprtsec is not set. Set xprtsec='tls' or 'mtls' in StorageClass."
            )
        if enforce_mtls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_mtls=True, "
                f"but xprtsec is not set. Set xprtsec='mtls' in StorageClass."
            )
        return

    # TLS mode: must have enforce_tls=True, enforce_mtls=False
    # For NFSv3: also requires enforce_tls_relaxed=True
    if xprtsec == "tls":
        if not enforce_tls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_tls=False, "
                f"but xprtsec='tls' requires nfs_enforce_tls=True."
            )
        if not is_nfs4 and not enforce_tls_relaxed:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_tls_relaxed=False, "
                f"but xprtsec='tls' with NFSv3 requires nfs_enforce_tls_relaxed=True."
            )
        if enforce_mtls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_mtls=True, "
                f"but xprtsec='tls' requires nfs_enforce_mtls=False. Use xprtsec='mtls' instead."
            )
        return

    # mTLS mode: must have enforce_tls=True, enforce_mtls=True
    # For NFSv3: also requires enforce_tls_relaxed=True
    if xprtsec == "mtls":
        if not enforce_tls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_tls=False, "
                f"but xprtsec='mtls' requires nfs_enforce_tls=True."
            )
        if not is_nfs4 and not enforce_tls_relaxed:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_tls_relaxed=False, "
                f"but xprtsec='mtls' with NFSv3 requires nfs_enforce_tls_relaxed=True."
            )
        if not enforce_mtls:
            raise XprtsecValidationError(
                f"View policy '{policy_name}' has nfs_enforce_mtls=False, "
                f"but xprtsec='mtls' requires nfs_enforce_mtls=True."
            )
        return


def validate_xprtsec_settings(mount_options: str, vms_session, view_policy: str) -> None:
    """
    Validate xprtsec settings against view policy.

    Extracts xprtsec and NFS version from mount_options and validates that the view policy
    TLS settings are compatible.
    """
    if not view_policy:
        return

    xprtsec = get_xprtsec_from_mount_options(mount_options)
    is_nfs4 = is_ver_nfs4_present(mount_options)
    view_policy_obj = vms_session.viewpolicies.one(name=view_policy, fail_if_missing=True)
    validate_xprtsec_view_policy(view_policy_obj, xprtsec or "", is_nfs4=is_nfs4)


def get_mtls_manager(
    mtls_client_cert: str = None,
    mtls_client_privkey: str = None,
    mount_flags: str = "",
    cluster_name: str = None,
) -> "MtlsManager":
    """
    Factory function to create an MtlsManager instance.
    """
    config = Config()
    xprtsec = get_xprtsec_from_mount_options(mount_flags)

    return MtlsManager.create(
        config=config,
        mtls_client_cert=mtls_client_cert,
        mtls_client_privkey=mtls_client_privkey,
        xprtsec=xprtsec,
        cluster_name=cluster_name,
    )


class MtlsManager(SerializationMixin):
    """Manages mTLS credentials and kernel keyring operations for NFS mount authentication."""

    def __init__(
        self,
        mtls_client_cert: str = None,
        mtls_client_privkey: str = None,
        xprtsec: str = "",
    ):
        self.mtls_client_cert = mtls_client_cert
        self.mtls_client_privkey = mtls_client_privkey
        self.xprtsec = xprtsec

    @classmethod
    def create(
        cls,
        config,
        mtls_client_cert,
        mtls_client_privkey,
        xprtsec,
        cluster_name,
    ):
        """
        Creates an MtlsManager instance, resolving mTLS credentials from
        arguments or secret-based configuration.

        If `cluster_name` is provided, credentials are loaded from a multi-cluster YAML config.
        If not, and no credentials are given, it falls back to the deprecated global secret.

        Args:
            config (Config): The configuration object containing secret paths and settings.
            mtls_client_cert (str, optional): PEM-formatted client certificate. If not provided,
                it will be resolved from secret configuration.
            mtls_client_privkey (str, optional): PEM-formatted client private key. If not provided,
                it will be resolved from secret configuration.
            xprtsec (str): NFS transport security mode ("", "tls", or "mtls").
            cluster_name (str, optional): The cluster name to use when resolving secrets
                from a multi-cluster configuration.

        Behavior:
            The credentials are resolved based on the following logic:

            1. **StorageClass Secret (Recommended)**:
                If `cluster_name` is not provided and `mtls_client_cert` and `mtls_client_privkey`
                are explicitly passed, they are used directly. This is the preferred method.

            2. **Multi-Cluster Secret**:
                If `cluster_name` is provided, the credentials are read from a YAML config mounted
                at `/opt/vms-auth/clusters`, where each top-level key is a cluster name. For example:

                ```yaml
                cluster1:
                  mtls_client_cert: |
                    -----BEGIN CERTIFICATE-----
                    ...
                    -----END CERTIFICATE-----
                  mtls_client_privkey: |
                    -----BEGIN RSA PRIVATE KEY-----
                    ...
                    -----END RSA PRIVATE KEY-----
                cluster2:
                  mtls_client_cert: ...
                  mtls_client_privkey: ...
                ```

            3. **Global Secret (Deprecated)**:
                If neither `cluster_name` nor direct credentials are provided,
                the credentials are loaded from the global secret (e.g., `/opt/vms-auth/mtls_client_cert`).
                This method is discouraged and retained for backward compatibility.

        Returns:
            MtlsManager: A configured instance with mTLS credentials for the specified volume.

        Raises:
            LookupFieldError: If a required value like the credentials is missing from the expected source.
        """
        if not xprtsec:
            # No transport security, return an empty manager
            return cls(
                mtls_client_cert=None,
                mtls_client_privkey=None,
                xprtsec="",
            )

        if xprtsec == "tls":
            # TLS-only mode: server authentication, no client credentials needed
            return cls(
                mtls_client_cert=None,
                mtls_client_privkey=None,
                xprtsec="tls",
            )

        # xprtsec == "mtls": mutual TLS, client credentials required
        if cluster_name:
            if not (
                cluster_auth_config := config.cluster_credentials.get(cluster_name)
            ):
                raise LookupFieldError(
                    field="cluster_name",
                    tip="Make sure cluster name is present in secret.",
                )
            mtls_client_cert = cluster_auth_config.get("mtls_client_cert")
            mtls_client_privkey = cluster_auth_config.get("mtls_client_privkey")
        else:
            # The presence of BOTH credentials in the arguments already indicates
            # that we have a StorageClass scope secret at this point.
            # In other words, it's not a globally mounted secret. Other secret fields will be validated below.
            is_global = not bool(mtls_client_cert and mtls_client_privkey)
            if config.vms_credentials_store.exists() and is_global:
                if config.vms_credentials_store["mtls_client_cert"].exists():
                    mtls_client_cert = (
                        config.vms_credentials_store["mtls_client_cert"].read().strip()
                    )
                if config.vms_credentials_store["mtls_client_privkey"].exists():
                    mtls_client_privkey = (
                        config.vms_credentials_store["mtls_client_privkey"]
                        .read()
                        .strip()
                    )

        return cls(
            mtls_client_cert=mtls_client_cert,
            mtls_client_privkey=mtls_client_privkey,
            xprtsec=xprtsec,
        )

    def dump_data(self) -> object:
        """Serialize mTLS credentials for storage."""
        return {
            "mtls_client_cert": self.mtls_client_cert,
            "mtls_client_privkey": self.mtls_client_privkey,
            "xprtsec": self.xprtsec,
        }

    @staticmethod
    def load_data(data_fields: dict) -> "MtlsManager":
        """
        Reconstruct an object from deserialized data fields.

        Args:
            data_fields: The result of unpickling the stored internal state.

        Returns:
            An instance of the MtlsManager class.
        """
        return MtlsManager(**data_fields)

    def requires_tls(self) -> bool:
        """Check if any transport security (TLS or mTLS) is enabled."""
        return self.xprtsec in ("tls", "mtls")

    def requires_mtls(self) -> bool:
        """Check if mTLS is enabled (xprtsec=mtls)."""
        return self.xprtsec == "mtls"

    def has_credentials(self) -> bool:
        """Check if mTLS credentials are present."""
        return bool(self.mtls_client_cert and self.mtls_client_privkey)

    def to_mount_flags(self, volume_id: str) -> list:
        """
        Convert transport security settings to mount flags for NFS.
        
        For mTLS, the mode is determined automatically by credential presence:
        - No credentials in secret → relies on /etc/tlshd.conf for client certs
        - With credentials in secret → loads certs to .nfs: keyring

        Args:
            volume_id: Volume ID (used for keyring operations)

        Returns:
            list: Mount flags for TLS/mTLS or empty list if not enabled
        """
        if not self.xprtsec:
            return []

        if self.xprtsec == "tls":
            # TLS-only: server authentication, no client cert
            # xprtsec=tls is already in mountOptions from StorageClass, nothing extra needed
            logger.info("TLS mount for volume %s: Server authentication only (no client certificate)", volume_id)
            return []

        if self.xprtsec == "mtls":
            if not self.has_credentials():
                # No credentials - rely on tlshd.conf for client certs
                # xprtsec=mtls is already in mountOptions from StorageClass
                logger.info(
                    "mTLS mount for volume %s: No credentials in secret, "
                    "using tlshd.conf for client authentication", volume_id
                )
                return []
            
            # Credentials provided - load to .nfs: keyring
            # xprtsec=mtls is already in mountOptions, we only add cert/privkey serials
            logger.info(
                "mTLS mount for volume %s: Loading client certificate and private key "
                "from secret to .nfs: kernel keyring", volume_id
            )
            cert_serial, privkey_serial = load_mtls_credentials(
                cert_pem=self.mtls_client_cert,
                privkey_pem=self.mtls_client_privkey,
                volume_id=volume_id,
            )
            logger.info(
                "mTLS mount for volume %s: Adding mount options cert_serial=0x%x, privkey_serial=0x%x",
                volume_id, cert_serial, privkey_serial
            )
            return [
                f"cert_serial=0x{cert_serial:x}",
                f"privkey_serial=0x{privkey_serial:x}",
            ]

        return []

    @staticmethod
    def delete_credentials(volume_id: str) -> None:
        """
        Delete mTLS credentials from the .nfs: kernel keyring for a specific volume.
        
        Args:
            volume_id: Volume ID to identify which keys to delete
        """
        delete_mtls_credentials(volume_id)
