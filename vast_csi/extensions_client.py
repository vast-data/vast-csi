# Copyright 2026 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Client for the VAST extensions-controller gRPC service.

The extensions-controller serves a VastExtensions gRPC endpoint.  Python
connects as a gRPC client over TCP (operator) or a co-located unix
socket (standalone Helm chart).
"""

import socket
import ssl
import threading
from pathlib import Path

import grpc

from vast_csi.configuration import Config
from vast_csi.proto import vast_extensions_pb2, vast_extensions_pb2_grpc

# Must match auth.ServerTLSName in the extensions-controller.
_TLS_SERVER_NAME = "vast-extensions"
_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

# gRPC status codes that indicate the extensions-controller is temporarily
# unreachable rather than a logical error (not-found, invalid argument, etc.).
_CONNECTION_ERROR_CODES = frozenset({
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
})

_cache_lock = threading.Lock()
_cached_target = None
_cached_channel = None
_cached_stub = None


def _extensions_grpc_target() -> str:
    return Config().extensions_grpc_address


def _is_unix_target(target: str) -> bool:
    return target.startswith("unix:") or target.startswith("/")


def _tcp_host_port(target: str) -> tuple[str, int]:
    t = target
    if t.startswith("dns:///"):
        t = t[len("dns:///") :]
    host, sep, port = t.rpartition(":")
    if not sep:
        raise ValueError(f"TCP gRPC target must be host:port, got {target!r}")
    return host, int(port)


def _peer_cert_pem(host: str, port: int) -> bytes:
    """Return the server's TLS cert so grpcio can pin it (no InsecureSkipVerify)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.set_alpn_protocols(["h2"])
    except NotImplementedError:
        pass
    with socket.create_connection((host, port), timeout=5) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
    if not der:
        raise RuntimeError("VastExtensions server did not present a TLS certificate")
    return ssl.DER_cert_to_PEM_cert(der).encode()


def _sa_token_plugin(context, callback):
    try:
        token = Path(_SA_TOKEN_PATH).read_text().strip()
    except OSError as exc:
        callback(None, exc)
        return
    callback((("authorization", f"Bearer {token}"),), None)


def _new_channel(target: str) -> grpc.Channel:
    if _is_unix_target(target):
        return grpc.insecure_channel(target)

    host, port = _tcp_host_port(target)
    ssl_creds = grpc.ssl_channel_credentials(root_certificates=_peer_cert_pem(host, port))
    call_creds = grpc.metadata_call_credentials(_sa_token_plugin, name="sa-token")
    creds = grpc.composite_channel_credentials(ssl_creds, call_creds)
    return grpc.secure_channel(
        target,
        creds,
        options=(("grpc.ssl_target_name_override", _TLS_SERVER_NAME),),
    )


def _close_cached_channel() -> None:
    global _cached_target, _cached_channel, _cached_stub
    if _cached_channel is not None:
        _cached_channel.close()
    _cached_target = None
    _cached_channel = None
    _cached_stub = None


def _make_stub(*, refresh: bool = False) -> vast_extensions_pb2_grpc.VastExtensionsStub:
    target = _extensions_grpc_target()
    with _cache_lock:
        global _cached_target, _cached_channel, _cached_stub
        if refresh or _cached_stub is None or _cached_target != target:
            _close_cached_channel()
            _cached_channel = _new_channel(target)
            _cached_stub = vast_extensions_pb2_grpc.VastExtensionsStub(_cached_channel)
            _cached_target = target
        return _cached_stub


def _rpc(method_name: str, request):
    stub = _make_stub()
    try:
        return getattr(stub, method_name)(request)
    except grpc.RpcError as exc:
        if exc.code() not in _CONNECTION_ERROR_CODES:
            raise
        stub = _make_stub(refresh=True)
        return getattr(stub, method_name)(request)


def get_storage_class_tenant_guid(storage_class: str) -> str:
    """Return the VAST tenant GUID for *storage_class*.

    The extensions-controller resolves the tenant by querying the VAST VMS
    REST API via the VIP pool referenced in the StorageClass parameters
    (``vip_pool_name`` or ``vip_pool_fqdn``).  No protection-policy lookup
    is performed on either side.

    Args:
        storage_class: Kubernetes StorageClass name.

    Returns:
        The VAST tenant GUID string.

    Raises:
        grpc.RpcError: if the gRPC call fails (socket not available, VMS
            error, StorageClass not found, etc.).
    """
    resp = _rpc(
        "GetReplicationTenant",
        vast_extensions_pb2.GetReplicationTenantRequest(storage_class=storage_class),
    )
    return resp.tenant_guid


def resolve_secret(secret_name: str, secret_namespace: str) -> dict[str, str]:
    """Fetch a Kubernetes Secret via the extensions-controller.

    Returns the Secret data as a key/value map, matching CSI
    ``CreateVolumeRequest.secrets``

    Args:
        secret_name: Kubernetes Secret name.
        secret_namespace: Kubernetes Secret namespace.

    Returns:
        Mapping of secret data keys to string values.

    Raises:
        grpc.RpcError: if the gRPC call fails or the Secret is not found
            (codes.NOT_FOUND).
    """
    resp = _rpc(
        "ResolveSecret",
        vast_extensions_pb2.ResolveSecretRequest(
            secret_name=secret_name,
            secret_namespace=secret_namespace,
        ),
    )
    return dict(resp.secrets)


def resolve_cosi_bucket_auth(bucket_id: str) -> dict[str, str]:
    """Resolve VMS credentials for a COSI bucket_id via extensions-controller."""
    resp = _rpc(
        "ResolveCOSIBucketAuth",
        vast_extensions_pb2.ResolveCOSIBucketAuthRequest(bucket_id=bucket_id),
    )
    return dict(resp.secrets)


def get_tenant_guid_for_sibling(storage_class: str) -> str:
    """Return the VAST tenant GUID of the *other* StorageClass in the replication group.

    The replication group is resolved by looking up which
    VastStorageClassReplication or VastVolumeReplication owns *storage_class*.
    The first StorageClass in that group that is not *storage_class* is treated
    as the sibling (i.e. the remote / destination cluster's StorageClass), and
    its tenant GUID is returned.

    This is used when setting up cross-cluster replication to identify the
    tenant on the destination VAST cluster.

    Args:
        storage_class: The local Kubernetes StorageClass name.

    Returns:
        The VAST tenant GUID string for the sibling StorageClass.

    Raises:
        grpc.RpcError: if either gRPC call fails.
        ValueError: if the replication group contains no StorageClass other
            than *storage_class* (degenerate single-member group).
    """
    info = get_replication_info(storage_class)
    sibling = next((sc for sc in info.storage_classes if sc != storage_class), None)
    if sibling is None:
        raise ValueError(
            f"No sibling StorageClass found for {storage_class!r} "
            f"in replication group {info.resource_kind}/{info.resource_name}"
        )
    return get_storage_class_tenant_guid(sibling)


def get_replication_info(
    storage_class: str,
    namespace: str = "",
) -> vast_extensions_pb2.GetReplicationInfoResponse:
    """Return the replication object that owns *storage_class*.

    Queries the extensions-controller for the VastStorageClassReplication or
    VastVolumeReplication that contains *storage_class* and returns the
    response message, which includes:

    * ``resource_name`` — name of the owning VSCR or VVR object
    * ``namespace`` — namespace of the owning object
    * ``resource_kind`` — ``"VastStorageClassReplication"`` or ``"VastVolumeReplication"``
    * ``is_primary`` — whether *storage_class* is the primary one in the group
    * ``storage_classes`` — all StorageClass names in the replication group
    * ``failover_type`` — the failover type configured on the owning resource

    Args:
        storage_class: Kubernetes StorageClass name to look up.
        namespace: Restrict the search to this namespace; empty means all namespaces.

    Raises:
        grpc.RpcError: if the gRPC call fails or the StorageClass is not found
            (codes.NOT_FOUND).
    """
    return _rpc(
        "GetReplicationInfo",
        vast_extensions_pb2.GetReplicationInfoRequest(
            storage_class=storage_class,
            namespace=namespace,
        ),
    )


def is_primary_storage_class(storage_class: str) -> bool:
    """Return whether *storage_class* is the primary StorageClass in its replication group."""
    info = get_replication_info(storage_class)
    return info.is_primary


# Maps proto FailoverType enum values to the CRD failoverType strings used by
# the CLI and the Kubernetes API (e.g. spec.failoverType on VSCR / VVR objects).
_FAILOVER_TYPE_NAMES: dict[int, str] = {
    vast_extensions_pb2.FAILOVER_TYPE_UNGRACEFUL: "ungraceful",
    vast_extensions_pb2.FAILOVER_TYPE_GRACEFUL: "graceful",
}


def get_failover_type(storage_class: str) -> str:
    """Return the failover type configured for *storage_class*.

    Returns:
        ``"ungraceful"`` or ``"graceful"``.

    Raises:
        grpc.RpcError: if the gRPC call fails or the StorageClass is not found.
        KeyError: if the server returns an unrecognised failover_type value.
    """
    info = get_replication_info(storage_class)
    return _FAILOVER_TYPE_NAMES[info.failover_type]


def get_failover_type_if_available(storage_class: str) -> "str | None":
    """Return the failover type for *storage_class*, or ``None`` if the
    extensions-controller is unreachable.

    Args:
        storage_class: Kubernetes StorageClass name.

    Returns:
        ``"ungraceful"`` or ``"graceful"``, or ``None`` when the controller
        socket is not yet available.

    Raises:
        grpc.RpcError: for any non-connectivity gRPC error.
    """
    try:
        return get_failover_type(storage_class)
    except grpc.RpcError as exc:
        if exc.code() in _CONNECTION_ERROR_CODES:
            return None
        raise
    except OSError:
        return None
