import base64
import json
import os
import pickle

import pytest
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from vast_csi.configuration import Config
from vast_csi.luks_utils import LuksManager
from vast_csi.serialization_utils import FORMAT_ENCRYPTED, FORMAT_PLAIN, SerializationError
from vast_csi.session import VmsSession


def encrypt_legacy_meta(obj, salt: str) -> str:
    """Reproduce the pre-tmpfs AES-CFB+pickle blob for fallback deserialization tests."""
    raw = pickle.dumps(obj.dump_data())
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(salt.encode("utf-8"))
    key = digest.finalize()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(raw) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("utf-8")


@pytest.fixture
def cred_key():
    return b"test-installation-secret-key-32bytes!"


@pytest.fixture
def volume_id():
    return "pvc-test-volume-id"


@pytest.fixture
def vms_session():
    config = Config()
    return VmsSession.create(
        config=config,
        username="user",
        password="pass",
        token=None,
        tenant="tenant",
        endpoint="vast.example.com",
        ssl_cert=None,
        cluster_name="cluster",
    )


def test_encrypted_round_trip(vms_session, volume_id, cred_key):
    payload = vms_session.serialize(volume_id, cred_key=cred_key)
    assert payload["format"] == FORMAT_ENCRYPTED

    restored = VmsSession.deserialize(
        volume_id, payload, cred_key=cred_key, fallback_to_deser=False,
    )
    assert restored.username == vms_session.username
    assert restored.password == vms_session.password
    assert restored.endpoint == vms_session.endpoint


def test_plaintext_when_no_secret(vms_session, volume_id):
    payload = vms_session.serialize(volume_id, cred_key=None)
    assert payload["format"] == FORMAT_PLAIN
    assert payload["username"] == vms_session.username

    restored = VmsSession.deserialize(
        volume_id, payload, cred_key=None, fallback_to_deser=False,
    )
    assert restored.password == vms_session.password


def test_legacy_pickle_rejected_when_fallback_disabled(vms_session, volume_id):
    legacy_blob = encrypt_legacy_meta(vms_session, volume_id)

    with pytest.raises(SerializationError, match="legacy serialized metadata rejected"):
        VmsSession.deserialize(
            volume_id, legacy_blob, cred_key=None, fallback_to_deser=False,
        )


def test_legacy_pickle_accepted_when_fallback_enabled(vms_session, volume_id):
    legacy_blob = encrypt_legacy_meta(vms_session, volume_id)

    restored = VmsSession.deserialize(
        volume_id, legacy_blob, cred_key=None, fallback_to_deser=True,
    )
    assert restored.username == vms_session.username


def test_malicious_pickle_rejected_when_fallback_disabled(volume_id):
    import os

    malicious = pickle.dumps({"oops": "not-a-session"})
    digest = hashes.Hash(hashes.SHA256(), backend=default_backend())
    digest.update(volume_id.encode("utf-8"))
    key = digest.finalize()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(malicious) + encryptor.finalize()
    legacy_blob = base64.b64encode(iv + ciphertext).decode("ascii")

    with pytest.raises(SerializationError):
        VmsSession.deserialize(
            volume_id, legacy_blob, cred_key=None, fallback_to_deser=False,
        )


def test_luks_manager_encrypted_round_trip(volume_id, cred_key):
    manager = LuksManager(
        volume_id=volume_id,
        passphrase="secret-passphrase",
        encryption_config={"cipher": "aes-xts-plain64"},
    )
    payload = manager.serialize(volume_id, cred_key=cred_key)
    restored = LuksManager.deserialize(
        volume_id, payload, cred_key=cred_key, fallback_to_deser=False,
    )
    assert restored.passphrase == manager.passphrase
    assert restored.encryption_config == manager.encryption_config


def test_meta_file_json_shape(vms_session, volume_id, cred_key):
    session_payload = vms_session.serialize(volume_id, cred_key=cred_key)
    meta = {
        "volume_id": volume_id,
        "is_ephemeral": True,
        "vms_session": session_payload,
    }
    loaded = json.loads(json.dumps(meta))
    assert isinstance(loaded["vms_session"], dict)
    assert loaded["vms_session"]["format"] == FORMAT_ENCRYPTED
