import unittest
import pytest
from plumbum import local
from unittest.mock import patch, MagicMock
from vast_csi.luks_utils import LuksManager
from vast_csi.exceptions import Abort, LookupFieldError
from vast_csi.configuration import Config


class TestLuksManager(unittest.TestCase):

    def setUp(self):
        self.volume_id = "vol-123"
        self.passphrase = "secret"
        self.context = {
            "host_encryption.cipher": "aes-xts-plain64"
        }

    def test_requires_encryption_true(self):
        manager = LuksManager(self.volume_id, passphrase=self.passphrase, encryption_config=self.context)
        self.assertTrue(manager.requires_encryption())

    def test_requires_encryption_abort(self):
        manager = LuksManager(self.volume_id, passphrase=None, encryption_config=self.context)
        with self.assertRaises(Abort):
            manager.requires_encryption()

    def test_create_with_explicit_passphrase(self):
        config = MagicMock(spec=Config)
        manager = LuksManager.create(config, self.volume_id, passphrase=self.passphrase, encryption_config={}, cluster_name=None)
        self.assertEqual(manager.passphrase, self.passphrase)

    def test_create_from_multicluster(self):
        config = MagicMock(spec=Config)
        config.cluster_credentials = {"cluster1": {"passphrase": "multi-secret"}}
        manager = LuksManager.create(config, self.volume_id, passphrase=None, encryption_config={}, cluster_name="cluster1")
        self.assertEqual(manager.passphrase, "multi-secret")

    def test_create_multicluster_missing(self):
        config = MagicMock(spec=Config)
        config.cluster_credentials = {}
        with self.assertRaises(LookupFieldError):
            LuksManager.create(config, self.volume_id, passphrase=None, encryption_config={}, cluster_name="missing")

    def test_create_from_global_secret(self):
        config = MagicMock(spec=Config)
        config.vms_credentials_store.exists.return_value = True
        config.host_encryption_passphrase = "global-secret"
        manager = LuksManager.create(config, self.volume_id, passphrase=None, encryption_config={}, cluster_name=None)
        self.assertEqual(manager.passphrase, "global-secret")

# -------------------------------
# Create from arguments or secret
# -------------------------------
class TestLuksManagerInit:

    def test_missing_device_path(self, config):
        lm = LuksManager.create(
            volume_id="vol123",
            passphrase=None,
            encryption_config={},
            config=config,
            cluster_name=None,
        )
        assert lm.passphrase is None

    def test_missing_passphrase(self, config):
        lm = LuksManager.create(
            volume_id="vol123",
            passphrase=None,
            encryption_config={"devicePath": "/dev/nvme0n1"},
            config=config,
            cluster_name=None,
        )
        assert lm.passphrase is None

    def test_instantiate_from_passphrase(self, config):
        mgr = LuksManager.create(
            volume_id="vol123",
            passphrase="supersecret",
            encryption_config={"devicePath": "/dev/nvme0n1"},
            config=config,
            cluster_name=None,
        )
        assert mgr.volume_id == "vol123"
        assert mgr.passphrase == "supersecret"
        assert mgr.encryption_config["devicePath"] == "/dev/nvme0n1"

    def test_cluster_secret_resolution(self, config):
        config.cluster_credentials = {
            "cluster1": {"passphrase": "xyz"}
        }
        mgr = LuksManager.create(
            config=config,
            volume_id="vol123",
            passphrase=None,
            encryption_config={"devicePath": "/dev/a"},
            cluster_name="cluster1"
        )
        assert mgr.passphrase == "xyz"

    def test_invalid_cluster_name(self, config):
        config.cluster_credentials = {}
        with pytest.raises(LookupFieldError, match="cluster name is present in secret"):
            LuksManager.create(
                config=config,
                volume_id="volX",
                passphrase=None,
                encryption_config={"devicePath": "/dev/a"},
                cluster_name="nonexistent"
            )

    def test_fallback_to_global_secret(self, config, tmpdir):
        global_path = tmpdir.mkdir("auth")
        global_path.join("passphrase").write("fallback")
        config.vms_credentials_store = local.path(global_path)

        mgr = LuksManager.create(
            config=config,
            volume_id="v123",
            passphrase=None,
            encryption_config={"devicePath": "/dev/zzz"},
            cluster_name=None
        )
        assert mgr.passphrase == "fallback"


# -------------------------------
# Serialize / Deserialize
# -------------------------------

def test_serialize_and_deserialize():
    mgr = LuksManager(volume_id="v123", passphrase="abc", encryption_config={"devicePath": "/dev/z"})
    salt = "somesalt"
    encoded = mgr.serialize(salt)
    loaded = LuksManager.deserialize(salt, encoded)
    assert loaded.volume_id == "v123"
    assert loaded.passphrase == "abc"
    assert loaded.encryption_config["devicePath"] == "/dev/z"


# -------------------------------
# Validation and parsing
# -------------------------------

def test_requires_encryption_with_passphrase():
    mgr = LuksManager("v1", "secret", {})
    assert mgr.requires_encryption() is True

def test_requires_encryption_with_config_and_missing_passphrase():
    mgr = LuksManager("v2", None, {"host_encryption.luks_type": "luks2"})
    with pytest.raises(Abort, match="Encryption config is present"):
        mgr.requires_encryption()

def test_requires_encryption_disabled():
    mgr = LuksManager("v3", None, {})
    assert mgr.requires_encryption() is False

def test_require_passphrase_raises_abort():
    mgr = LuksManager("v4", None, {})
    with pytest.raises(Abort, match="Passphrase must be provided"):
        mgr._require_passphrase()
