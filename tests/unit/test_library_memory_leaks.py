"""
Steady-state memory checks for the third-party libraries on the plugin's RPC path.

Two heaps are measured per round:

* Python objects, via ``tracemalloc`` (``get_traced_memory()[0]``).
* Everything glibc has handed out and not yet got back, via ``mallinfo2()``
  (``uordblks`` in all arenas + ``hblkhd`` mmap'd blocks). This counts bytes
  still allocated, so it sees a C-level leak but is blind to arena
  fragmentation, which is exactly the separation VCSI-702 needed.

Run with:
    pytest -m memleak tests/unit/test_library_memory_leaks.py -v -s
"""

import ctypes
import datetime
import gc
import ipaddress
import json
import ssl
import subprocess
import sys
import threading
import time
import tracemalloc
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import grpc
import pytest
import requests
import yaml
from concurrent import futures
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from easypy.bunch import Bunch
from easypy.misc import kwargs_resilient
from filelock import FileLock
from google.protobuf.json_format import MessageToDict

import vast_csi.csi_types as types
import vast_csi.metrics as metrics
import vast_csi.plugins.base as plugin_base
from vast_csi.lru_cache import _cache_region, cache_on_arguments
from vast_csi.metrics import get_metrics_registry
from vast_csi.plugins.nfs import CsiIdentity
from vast_csi.proto import csi_pb2, csi_pb2_grpc
from vast_csi.session import get_vms_session, instantiate_session_from_secret
from vast_csi.session.base import PinnedSSLContextAdapter, build_ssl_context
from vast_csi.utils import stringify_dict

pytestmark = pytest.mark.memleak

KiB = 1024
ROOT = Path(__file__).resolve().parents[2]


# ----------------------------------------------------------------------------------------------------------------------
# Measurement helpers
# ----------------------------------------------------------------------------------------------------------------------


class _Mallinfo2(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_size_t)
        for name in (
            "arena", "ordblks", "smblks", "hblks", "hblkhd",
            "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost",
        )
    ]


def _load_mallinfo2():
    try:
        libc = ctypes.CDLL("libc.so.6")
        fn = libc.mallinfo2
    except (OSError, AttributeError):
        return None
    fn.argtypes = []
    fn.restype = _Mallinfo2
    return fn


_MALLINFO2 = _load_mallinfo2()


def native_in_use():
    """Bytes currently allocated from glibc across all arenas, or None when mallinfo2 is unavailable."""
    if _MALLINFO2 is None:
        return None
    info = _MALLINFO2()
    return info.uordblks + info.hblkhd


def _measure():
    gc.collect()
    gc.collect()
    return tracemalloc.get_traced_memory()[0], native_in_use()


def assert_steady_state(
    step,
    *,
    label,
    warmup=2,
    rounds=6,
    py_tolerance=32 * KiB,
    native_tolerance=256 * KiB,
):
    """Run ``step`` repeatedly and fail if memory grows on every one of the last three rounds.

    Returns the per-round deltas so a test can print them with ``-s``.
    """
    already_tracing = tracemalloc.is_tracing()
    if not already_tracing:
        tracemalloc.start()
    try:
        for _ in range(warmup):
            step()
        prev_py, prev_native = _measure()
        py_deltas, native_deltas = [], []
        for _ in range(rounds):
            step()
            py, native = _measure()
            py_deltas.append(py - prev_py)
            if native is not None:
                native_deltas.append(native - prev_native)
            prev_py, prev_native = py, native
    finally:
        if not already_tracing:
            tracemalloc.stop()

    def fmt(deltas):
        return ", ".join(f"{d / KiB:+.1f}" for d in deltas) + " KiB"

    report = f"{label}: python per round [{fmt(py_deltas)}]"
    if native_deltas:
        report += f"; native in-use per round [{fmt(native_deltas)}]"
    print(report)

    tail = py_deltas[-3:]
    assert not all(d > py_tolerance for d in tail), f"Python heap keeps growing. {report}"
    if native_deltas:
        tail = native_deltas[-3:]
        assert not all(d > native_tolerance for d in tail), f"Native heap keeps growing. {report}"
    return py_deltas, native_deltas


def _ensure_metric_factory():
    """Prometheus metrics register once per process; reuse the factory if an earlier test created it."""
    if metrics.METRIC_FACTORY is None:
        metrics.METRIC_FACTORY = metrics.MetricFactory(is_node_service=False)
    return metrics.METRIC_FACTORY


# ----------------------------------------------------------------------------------------------------------------------
# Local TLS server (cryptography + ssl + http.server)
# ----------------------------------------------------------------------------------------------------------------------


def _self_signed_cert(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class _JsonHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    close_connection_after_response = False
    body = json.dumps({"results": [{"id": i, "name": f"view-{i}"} for i in range(50)]}).encode()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        if self.close_connection_after_response:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(self.body)
        if self.close_connection_after_response:
            self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.do_GET()

    def log_message(self, *args):
        pass


@pytest.fixture
def tls_server(tmp_path):
    """Yield (base_url, ca_path, handler_cls) for a local HTTPS server."""
    cert_path, key_path = _self_signed_cert(tmp_path)
    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

    class Handler(_JsonHandler):
        pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    httpd.socket = server_ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}", cert_path, Handler
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _pinned_session(ca_path):
    """The HTTPS stack exactly as RESTSession.pin_ssl_context mounts it."""
    session = requests.Session()
    session.mount("https://", PinnedSSLContextAdapter(build_ssl_context(str(ca_path))))
    session.headers["Accept"] = "application/json"
    return session


# ----------------------------------------------------------------------------------------------------------------------
# requests / urllib3 / ssl / OpenSSL
# ----------------------------------------------------------------------------------------------------------------------


def test_requests_pinned_context_keepalive(tls_server):
    """Repeated verified HTTPS calls over a pooled connection: the VMS REST client path."""
    base_url, ca_path, _ = tls_server
    session = _pinned_session(ca_path)

    def step():
        for i in range(200):
            resp = session.get(f"{base_url}/api/v1/views/", params={"page": i}, timeout=5)
            resp.raise_for_status()
            resp.json()
            resp.close()

    try:
        assert_steady_state(step, label="requests keep-alive HTTPS")
    finally:
        session.close()


def test_requests_pinned_context_reconnect_each_request(tls_server):
    """Server closes after every response, so each request does a full TLS handshake.

    This is where SSL session caching or SSL object leaks (OpenSSL, CPython ssl, urllib3
    connection objects) would surface.
    """
    base_url, ca_path, handler = tls_server
    handler.close_connection_after_response = True
    session = _pinned_session(ca_path)

    def step():
        for i in range(100):
            resp = session.post(f"{base_url}/api/v1/views/", data=json.dumps({"n": i}), timeout=5)
            resp.raise_for_status()
            resp.json()

    try:
        assert_steady_state(step, label="requests reconnect-per-request HTTPS")
    finally:
        session.close()


def test_requests_session_create_and_close(tls_server):
    """Building and discarding whole sessions (adapter + pool manager + SSLContext) must not accumulate."""
    base_url, ca_path, _ = tls_server

    def step():
        for _ in range(30):
            session = _pinned_session(ca_path)
            session.get(f"{base_url}/api/v1/views/", timeout=5).raise_for_status()
            session.close()

    assert_steady_state(step, label="requests session churn")


# ----------------------------------------------------------------------------------------------------------------------
# grpcio through the Instrumented wrapper
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def grpc_identity_server(tmp_path, monkeypatch):
    """A real grpc.server on a unix socket serving CsiIdentity with the Instrumented wrapper active.

    conftest strips the wrapper from Controller/Node classes but leaves CsiIdentity alone, so these
    RPCs exercise the exact per-request path (ListFields, metrics registry, logging) of production.
    """
    _ensure_metric_factory()
    monkeypatch.setattr(
        plugin_base,
        "CONF",
        SimpleNamespace(
            static_provisioning=False,
            metrics_enabled=True,
            node_id="unit-node",
            plugin_name="csi.vastdata.com",
            plugin_version="0.0.0",
        ),
    )
    identity = CsiIdentity()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    csi_pb2_grpc.add_IdentityServicer_to_server(identity, server)
    address = f"unix:{tmp_path / 'csi.sock'}"
    server.add_insecure_port(address)
    server.start()
    try:
        yield address
    finally:
        server.stop(grace=None)


def test_grpc_unary_rpcs_persistent_channel(grpc_identity_server):
    """What kubelet/sidecars do: one long-lived channel, many unary calls."""
    with grpc.insecure_channel(grpc_identity_server) as channel:
        stub = csi_pb2_grpc.IdentityStub(channel)

        def step():
            for _ in range(150):
                stub.Probe(csi_pb2.ProbeRequest())
                stub.GetPluginInfo(csi_pb2.GetPluginInfoRequest())
                stub.GetPluginCapabilities(csi_pb2.GetPluginCapabilitiesRequest())

        assert_steady_state(step, label="grpc unary over persistent channel", native_tolerance=512 * KiB)


_GRPC_CHURN_CLIENT = """
import sys, grpc
sys.path.insert(0, {root!r})
from vast_csi.proto import csi_pb2, csi_pb2_grpc
for _ in range(40):
    with grpc.insecure_channel({address!r}) as channel:
        stub = csi_pb2_grpc.IdentityStub(channel)
        stub.Probe(csi_pb2.ProbeRequest(), timeout=5)
        stub.GetPluginInfo(csi_pb2.GetPluginInfoRequest(), timeout=5)
"""


def test_grpc_server_side_connection_churn(grpc_identity_server):
    """Clients that reconnect on every call (csi livenessprobe does): a new transport per call on the server.

    The client runs in a subprocess so only the server process, which is what the plugin is, gets
    measured. grpc's client-side global subchannel pool tears down asynchronously and would otherwise
    add noise that has nothing to do with the plugin.
    """
    client = _GRPC_CHURN_CLIENT.format(root=str(ROOT), address=grpc_identity_server)

    def step():
        subprocess.run([sys.executable, "-c", client], check=True)
        time.sleep(0.3)  # let the server finish tearing the transports down before measuring

    assert_steady_state(step, label="grpc server-side connection churn", warmup=3)


# ----------------------------------------------------------------------------------------------------------------------
# protobuf (upb)
# ----------------------------------------------------------------------------------------------------------------------


def _build_create_volume_request(i):
    return csi_pb2.CreateVolumeRequest(
        name=f"pvc-{i:08d}-0000-0000-0000-000000000000",
        capacity_range=csi_pb2.CapacityRange(required_bytes=1 << 30),
        volume_capabilities=[
            csi_pb2.VolumeCapability(
                mount=csi_pb2.VolumeCapability.MountVolume(fs_type="nfs", mount_flags=["vers=3", "nconnect=4"]),
                access_mode=csi_pb2.VolumeCapability.AccessMode(
                    mode=csi_pb2.VolumeCapability.AccessMode.MULTI_NODE_MULTI_WRITER
                ),
            )
        ],
        parameters={
            "vip_pool_name": "vippool-1",
            "view_policy": "default",
            "root_export": "/k8s",
            "csi.storage.k8s.io/pvc/name": f"claim-{i}",
            "csi.storage.k8s.io/pvc/namespace": "default",
        },
        secrets={"username": "admin", "password": "secret", "endpoint": "vms.example.com"},
    )


def test_protobuf_message_lifecycle():
    """Build, serialize, parse into a fresh message, ListFields, MessageToDict: the per-RPC protobuf work."""

    def step():
        for i in range(300):
            req = _build_create_volume_request(i)
            wire = req.SerializeToString()
            parsed = csi_pb2.CreateVolumeRequest()
            parsed.ParseFromString(wire)
            params = {fld.name: value for fld, value in parsed.ListFields()}
            assert params["name"] == req.name
            # the Instrumented wrapper stringifies params for logging
            list(stringify_dict({k: v for k, v in params.items() if k != "secrets"}))
            MessageToDict(parsed)
            resp = csi_pb2.CreateVolumeResponse(
                volume=csi_pb2.Volume(volume_id=req.name, capacity_bytes=1 << 30, volume_context=dict(req.parameters))
            )
            resp.SerializeToString()

    assert_steady_state(step, label="protobuf message lifecycle")


def test_protobuf_module_level_responses_are_immutable():
    """ProbeRespOK is shared by every Probe; returning it must not grow it."""
    before = types.ProbeRespOK.ByteSize()
    for _ in range(1000):
        assert types.ProbeRespOK.SerializeToString()
    assert types.ProbeRespOK.ByteSize() == before


# ----------------------------------------------------------------------------------------------------------------------
# dogpile.cache + cachetools (cache_on_arguments)
# ----------------------------------------------------------------------------------------------------------------------


class _FakeResource:
    def __init__(self, session_key):
        self.session = session_key  # hash(session) scopes the cache key

    @cache_on_arguments(expiration_time=300)
    def one(self, name, **params):
        return Bunch(name=name, payload="x" * 2048, **params)


def test_dogpile_region_is_bounded_under_unique_keys():
    """Every call uses a new key; the LRU backend must evict instead of growing."""
    backend_cache = _cache_region.backend._cache
    counter = [0]
    resource = _FakeResource(session_key=1)

    def step():
        for _ in range(500):
            counter[0] += 1
            resource.one(name=f"view-{counter[0]}", tenant_id=counter[0] % 7)
        assert len(backend_cache) <= backend_cache.maxsize

    assert_steady_state(step, label="dogpile cache_on_arguments unique keys")
    assert backend_cache.maxsize == 200


def test_dogpile_repeated_keys_hit_cache():
    resource = _FakeResource(session_key=2)
    first = resource.one(name="same")
    for _ in range(100):
        assert resource.one(name="same") is first
    _cache_region.invalidate()


# ----------------------------------------------------------------------------------------------------------------------
# easypy locking_cache on get_vms_session
# ----------------------------------------------------------------------------------------------------------------------


def test_vms_session_cache_memoizes_per_credentials(mock_credentials, monkeypatch):
    """Instrumented calls instantiate_session_from_secret on every RPC; the same secret must reuse one session.

    get_vms_session is an easypy locking_cache with no expiry: it is bounded by the number of
    distinct credential sets a cluster uses, not by the number of RPCs.
    """
    from vast_csi.configuration import Config

    monkeypatch.setattr(Config, "vms_credentials_store", mock_credentials)
    secrets = {"username": "admin", "password": "pw", "endpoint": "vms-a.example.com"}

    with patch("vast_csi.session.VmsSession.refresh_auth_token", MagicMock()):
        get_vms_session.cache_clear()
        first = instantiate_session_from_secret(secrets)

        def step():
            for _ in range(300):
                assert instantiate_session_from_secret(dict(secrets)) is first

        assert_steady_state(step, label="get_vms_session memoization")
        get_vms_session.cache_clear()


# ----------------------------------------------------------------------------------------------------------------------
# prometheus_client
# ----------------------------------------------------------------------------------------------------------------------


def test_prometheus_label_cardinality_is_bounded():
    """volume_id changes on every RPC but is not a label on the CSI operation metrics."""
    factory = _ensure_metric_factory()
    methods = ("CreateVolume", "DeleteVolume", "ControllerPublishVolume", "ControllerUnpublishVolume")
    counter = [0]
    children = factory.csi_operations_total._metrics
    series_before = set(children)

    def step():
        for _ in range(400):
            counter[0] += 1
            registry = get_metrics_registry(
                {"volume_id": f"pvc-{counter[0]}"}, hostname="unit-node", driver_name="csi.vastdata.com"
            )
            method = methods[counter[0] % len(methods)]
            try:
                with registry.csi_operation(method):
                    if counter[0] % 5 == 0:
                        raise plugin_base.Abort(grpc.StatusCode.NOT_FOUND, "no such volume")
            except plugin_base.Abort:
                pass

    assert_steady_state(step, label="prometheus csi_operation")
    # 400 * rounds distinct volume_ids collapse to (method x {OK, NotFound}) series.
    new_series = set(children) - series_before
    assert len(new_series) <= len(methods) * 2, f"unexpected label series: {sorted(new_series)}"


# ----------------------------------------------------------------------------------------------------------------------
# easypy, PyYAML, filelock, cryptography
# ----------------------------------------------------------------------------------------------------------------------


def test_easypy_bunch_and_kwargs_resilient():
    @kwargs_resilient
    def handler(request, context, vms_session=None):
        return request, context

    def step():
        for i in range(2000):
            data = Bunch.from_dict({"a": {"b": [1, 2, {"c": i}]}, "name": f"n{i}"})
            data.to_dict()
            handler(request=i, context=None, vms_session=None, extra=1, volume_id="x")

    assert_steady_state(step, label="easypy Bunch/kwargs_resilient")


def test_yaml_multicluster_secret_parse():
    doc = yaml.safe_dump({
        f"cluster{i}": {"username": f"u{i}", "password": "p", "endpoint": f"c{i}.example.com"} for i in range(20)
    })

    def step():
        for _ in range(200):
            Bunch.from_dict(yaml.safe_load(doc))

    assert_steady_state(step, label="PyYAML safe_load")


def test_filelock_acquire_release(tmp_path):
    lock_path = tmp_path / "volume.lock"

    def step():
        for _ in range(300):
            with FileLock(str(lock_path), timeout=5):
                pass

    assert_steady_state(step, label="filelock acquire/release")


def test_cryptography_pem_parse(tmp_path):
    cert_path, _ = _self_signed_cert(tmp_path)
    pem = cert_path.read_bytes()

    def step():
        for _ in range(300):
            cert = x509.load_pem_x509_certificate(pem)
            cert.fingerprint(hashes.SHA256())
            cert.public_bytes(serialization.Encoding.DER)

    assert_steady_state(step, label="cryptography x509 parse")
