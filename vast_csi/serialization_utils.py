import base64
import json
import os
import pickle
from abc import ABC, abstractmethod
from typing import Any, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vast_csi.logging import logger


FORMAT_LEGACY = "legacy"
FORMAT_ENCRYPTED = "encrypted"
FORMAT_PLAIN = "plain"


class SerializationError(Exception):
    """Raised when serialized metadata cannot be decoded safely."""


def _derive_key_legacy(salt: Union[str, bytes]) -> bytes:
    """
    Key derivation used by the previous CSI meta format.

    The AES key was SHA-256(volume_id) with no installation secret. Anyone who
    can read volume_id (it is on the node and in Kubernetes objects) can decrypt
    the blob. Kept only to unpublish EV volumes that were mounted before
    credSerializationSecret existed (fallbackToDeser).
    """
    if isinstance(salt, str):
        salt = salt.encode("utf-8")
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(salt)
    return digest.finalize()


def _derive_key(cred_key: bytes, volume_id: str) -> bytes:
    """
    Derive the AES-GCM key for the current meta format.

    Mixes the cluster-wide credSerializationSecret with volume_id via HKDF so:
    - the key cannot be computed from volume_id alone
    - each volume gets a distinct key from the same secret
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=cred_key,
        info=volume_id.encode("utf-8"),
        backend=default_backend(),
    ).derive(b"")


def _encrypt_gcm(key: bytes, plaintext: bytes) -> bytes:
    """
    Encrypt meta JSON with AES-GCM (current write path).

    GCM is authenticated encryption: decrypt fails if the blob was truncated
    or modified. Returns nonce (12 bytes) + ciphertext + GCM tag.
    """
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _decrypt_gcm(key: bytes, blob: bytes) -> bytes:
    """Decrypt a blob produced by ``_encrypt_gcm`` (nonce || ciphertext+tag)."""
    nonce, ciphertext = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _decrypt_legacy_cfb(key: bytes, blob: bytes) -> bytes:
    """
    Decrypt a blob produced by the previous CSI meta format (IV || AES-CFB).

    Needed to read pickle-encrypted credentials from EV volumes that were
    published before tmpfs + credSerializationSecret.
    """
    iv, ciphertext = blob[:16], blob[16:]
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


class SerializationMixin(ABC):
    """
    Serialize/deserialize driver metadata.

    Write paths:
      - cred_key set: JSON payload encrypted with AES-GCM (key = HKDF(cred_key, volume_id))
      - cred_key missing: plaintext JSON fields (logged warning)

    Read paths:
      - encrypted / plain JSON dict payloads
      - legacy base64 AES-CFB + pickle blobs when fallback_to_deser=True
    """

    @abstractmethod
    def dump_data(self) -> object:
        """Return JSON-serializable internal state."""
        pass

    @staticmethod
    @abstractmethod
    def load_data(data_fields: object) -> "SerializationMixin":
        """Reconstruct object from deserialized data fields."""
        pass

    def serialize(self, volume_id: str, cred_key: bytes = None) -> dict:
        """
        Serialize object state for storage in .vast-csi-meta.

        Returns a dict with a ``format`` field (never a raw legacy base64 string).
        """
        data = self.dump_data()
        if cred_key:
            plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
            key = _derive_key(cred_key, volume_id)
            blob = base64.b64encode(_encrypt_gcm(key, plaintext)).decode("ascii")
            return {"format": FORMAT_ENCRYPTED, "data": blob}

        logger.info(
            "credSerializationSecret is not configured; storing %s credentials as plaintext JSON",
            self.__class__.__name__,
        )
        return {"format": FORMAT_PLAIN, **data}

    @classmethod
    def deserialize(
        cls,
        volume_id: str,
        payload: Any,
        cred_key: bytes = None,
        fallback_to_deser: bool = False,
    ) -> "SerializationMixin":
        if isinstance(payload, str):
            if not fallback_to_deser:
                raise SerializationError(
                    "legacy serialized metadata rejected (fallbackToDeser=false)"
                )
            return cls.deserialize_legacy(volume_id, payload)

        if not isinstance(payload, dict):
            raise SerializationError(f"unsupported serialized payload type: {type(payload)!r}")

        fmt = payload.get("format")
        if fmt == FORMAT_PLAIN:
            fields = {k: v for k, v in payload.items() if k != "format"}
            return cls.load_data(fields)

        if fmt == FORMAT_ENCRYPTED:
            if not cred_key:
                raise SerializationError(
                    "encrypted metadata requires credSerializationSecret"
                )
            try:
                encrypted = base64.b64decode(payload["data"])
                key = _derive_key(cred_key, volume_id)
                raw = _decrypt_gcm(key, encrypted)
                fields = json.loads(raw.decode("utf-8"))
            except (InvalidTag, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise SerializationError(f"failed to decrypt metadata: {exc}") from exc
            return cls.load_data(fields)

        if fallback_to_deser:
            # Transitional: try encrypted without explicit format, then legacy string in data.
            if cred_key and "data" in payload and isinstance(payload["data"], str):
                try:
                    return cls.deserialize(
                        volume_id,
                        {"format": FORMAT_ENCRYPTED, "data": payload["data"]},
                        cred_key=cred_key,
                        fallback_to_deser=False,
                    )
                except SerializationError:
                    pass
            if isinstance(payload.get("data"), str):
                return cls.deserialize_legacy(volume_id, payload["data"])

        raise SerializationError(f"unknown serialized metadata format: {fmt!r}")

    @classmethod
    def deserialize_legacy(cls, volume_id: str, encrypted_blob: str) -> "SerializationMixin":
        """Legacy AES-CFB + pickle path (read-only, migration)."""
        try:
            encrypted_bytes = base64.b64decode(encrypted_blob)
            key = _derive_key_legacy(volume_id)
            raw_data = _decrypt_legacy_cfb(key, encrypted_bytes)
            return cls.load_data(pickle.loads(raw_data))
        except Exception as exc:
            raise SerializationError(f"legacy metadata deserialization failed: {exc}") from exc
