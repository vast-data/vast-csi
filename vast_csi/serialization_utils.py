import os
import pickle
import base64
from typing import Union
from abc import ABC, abstractmethod

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


def _derive_key_from_salt(salt: Union[str, bytes]) -> bytes:
    """
    Derive a 256-bit key using SHA-256 from the provided salt.

    Args:
        salt: A string or byte sequence used to derive the key.

    Returns:
        A 32-byte key.
    """
    if isinstance(salt, str):
        salt = salt.encode("utf-8")

    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(salt)
    return digest.finalize()


class SerializationMixin(ABC):
    """
    Mixin providing encrypted serialization and deserialization using AES-CFB.

    Classes must implement `dump_data()` and `load_data(data_fields)`.
    """

    @abstractmethod
    def dump_data(self) -> object:
        """
        Return the internal state of the object to be serialized.
        Must be pickle-serializable.
        """
        pass

    @staticmethod
    @abstractmethod
    def load_data(data_fields: object) -> "SerializationMixin":
        """
        Reconstruct an object from deserialized data fields.

        Args:
            data_fields: The result of unpickling the stored internal state.

        Returns:
            An instance of the implementing class.
        """
        pass

    def serialize(self, salt: str) -> str:
        """
        Serialize and encrypt the object's state using AES-CFB.

        Args:
            salt: A passphrase or salt used to derive the encryption key.

        Returns:
            Base64-encoded string of IV + ciphertext.
        """
        raw_data = pickle.dumps(self.dump_data())
        iv = os.urandom(16)
        key = _derive_key_from_salt(salt)

        cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(raw_data) + encryptor.finalize()

        encrypted_blob = iv + ciphertext
        return base64.b64encode(encrypted_blob).decode("utf-8")

    @classmethod
    def deserialize(cls, salt: str, encrypted_blob: str) -> "SerializationMixin":
        """
        Decrypt and deserialize an object instance from base64-encoded ciphertext.

        Args:
            salt: Passphrase or salt used to derive the decryption key.
            encrypted_blob: Base64-encoded string of IV + ciphertext.

        Returns:
            Reconstructed object.
        """
        encrypted_bytes = base64.b64decode(encrypted_blob)
        iv = encrypted_bytes[:16]
        ciphertext = encrypted_bytes[16:]

        key = _derive_key_from_salt(salt)
        cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        raw_data = decryptor.update(ciphertext) + decryptor.finalize()

        return cls.load_data(pickle.loads(raw_data))
