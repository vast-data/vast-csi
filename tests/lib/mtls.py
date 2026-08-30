"""NFS mTLS helpers for CSI e2e: PEM generation and K8s secret material."""
from __future__ import annotations

import datetime as dt
import ipaddress
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lib.constants import CSI_NAMESPACE


_TLS_CA_CN = "vast-csi-e2e-nfs-server-ca"
_MTLS_CA_CN = "vast-csi-e2e-nfs-client-ca"


@dataclass
class PemBundle:
    certificate_pem: str
    private_key_pem: str
    ca_pem: str


def _new_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn[:64])])


def _pem_cert(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _pem_key(key: rsa.RSAPrivateKey) -> str:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def build_ca(common_name: str) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = _new_key()
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(_name(common_name))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert, key


def build_leaf(
    *,
    ca_cert: x509.Certificate,
    ca_key: rsa.RSAPrivateKey,
    common_name: str,
    san_dns: Iterable[str] = (),
    san_ips: Iterable[str] = (),
) -> tuple[x509.Certificate, rsa.RSAPrivateKey]:
    key = _new_key()
    now = dt.datetime.now(dt.timezone.utc)
    sans: list[x509.GeneralName] = [
        *[x509.DNSName(d) for d in san_dns],
        *[x509.IPAddress(ipaddress.ip_address(ip)) for ip in san_ips],
    ]
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(common_name))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
    )
    if sans:
        builder = builder.add_extension(x509.SubjectAlternativeName(sans), critical=False)
    return builder.sign(ca_key, hashes.SHA256()), key


def build_nfs_mtls_material(vip_ips: list[str]) -> tuple[PemBundle, PemBundle]:
    """Return (server_bundle, client_bundle).

    ``server_bundle.ca_pem`` goes to tlshd truststore.
    ``server_bundle`` cert/key go to cluster ``nfs4_certificate`` / ``nfs4_private_key``.
    ``client_bundle.ca_pem`` is uploaded as the tenant NFS mTLS CA.
    ``client_bundle`` cert/key go into the StorageClass secret.
    """
    server_ca, server_ca_key = build_ca(_TLS_CA_CN)
    server_cert, server_key = build_leaf(
        ca_cert=server_ca,
        ca_key=server_ca_key,
        common_name="vast-csi-e2e-nfs-server",
        san_ips=vip_ips,
    )
    server = PemBundle(
        certificate_pem=_pem_cert(server_cert),
        private_key_pem=_pem_key(server_key),
        ca_pem=_pem_cert(server_ca),
    )

    client_ca, client_ca_key = build_ca(_MTLS_CA_CN)
    client_cert, client_key = build_leaf(
        ca_cert=client_ca,
        ca_key=client_ca_key,
        common_name="vast-csi-e2e-nfs-client",
    )
    client = PemBundle(
        certificate_pem=_pem_cert(client_cert),
        private_key_pem=_pem_key(client_key),
        ca_pem=_pem_cert(client_ca),
    )
    return server, client


def create_mgmt_secret_with_mtls(
    k8s,
    *,
    name: str,
    system,
    client: PemBundle,
    namespace: str = CSI_NAMESPACE,
) -> str:
    """Create a StorageClass secret that includes mTLS client PEM material."""
    with tempfile.TemporaryDirectory(prefix="csi-mtls-") as tmp:
        tmp_path = Path(tmp)
        cert_path = tmp_path / "mtls_client_cert"
        key_path = tmp_path / "mtls_client_privkey"
        cert_path.write_text(client.certificate_pem)
        key_path.write_text(client.private_key_pem)
        return k8s.secrets.create(
            namespace,
            name=name,
            username=system.username,
            password=system.password,
            endpoint=system.endpoint,
            files={
                "mtls_client_cert": str(cert_path),
                "mtls_client_privkey": str(key_path),
            },
        )
