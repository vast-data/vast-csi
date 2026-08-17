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

import grpc

from vast_csi.configuration import Config
from vast_csi.proto import vast_extensions_pb2, vast_extensions_pb2_grpc


def _extensions_grpc_target() -> str:
    return Config().extensions_grpc_address


def _make_stub() -> vast_extensions_pb2_grpc.VastExtensionsStub:
    channel = grpc.insecure_channel(_extensions_grpc_target())
    return vast_extensions_pb2_grpc.VastExtensionsStub(channel)


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
    stub = _make_stub()
    resp = stub.GetReplicationTenant(
        vast_extensions_pb2.GetReplicationTenantRequest(
            storage_class=storage_class,
        )
    )
    return resp.tenant_guid


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
    stub = _make_stub()
    return stub.GetReplicationInfo(
        vast_extensions_pb2.GetReplicationInfoRequest(
            storage_class=storage_class,
            namespace=namespace,
        )
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


# gRPC status codes that indicate the extensions-controller is temporarily
# unreachable rather than a logical error (not-found, invalid argument, etc.).
_CONNECTION_ERROR_CODES = frozenset({
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
})


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
