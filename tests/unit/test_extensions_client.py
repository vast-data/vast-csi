import pytest

from vast_csi import extensions_client as ec


def test_load_ca_pem_reads_mounted_bundle(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("X_CSI_EXTENSIONS_GRPC_CA_CERT", str(ca))
    assert ec._load_ca_pem().startswith(b"-----BEGIN CERTIFICATE-----")


def test_load_ca_pem_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("X_CSI_EXTENSIONS_GRPC_CA_CERT", str(tmp_path / "missing.crt"))
    with pytest.raises(RuntimeError, match="CA certificate not found"):
        ec._load_ca_pem()


def test_new_channel_tcp_uses_mounted_ca(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("X_CSI_EXTENSIONS_GRPC_CA_CERT", str(ca))
    # Channel construction must not call an unverified peer-cert fetch.
    channel = ec._new_channel("extensions-manager-grpc.vast-csi.svc:9090")
    assert channel is not None
    channel.close()


def test_new_channel_unix_uses_mounted_ca(tmp_path, monkeypatch):
    ca = tmp_path / "ca.crt"
    ca.write_bytes(b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    monkeypatch.setenv("X_CSI_EXTENSIONS_GRPC_CA_CERT", str(ca))
    channel = ec._new_channel("unix:///var/run/vast-extensions/extensions.sock")
    assert channel is not None
    channel.close()


def test_new_channel_unix_requires_ca(tmp_path, monkeypatch):
    monkeypatch.setenv("X_CSI_EXTENSIONS_GRPC_CA_CERT", str(tmp_path / "missing.crt"))
    with pytest.raises(RuntimeError, match="CA certificate not found"):
        ec._new_channel("unix:///var/run/vast-extensions/extensions.sock")
