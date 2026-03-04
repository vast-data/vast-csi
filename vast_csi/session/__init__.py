"""
VAST CSI Session Package.

This package provides session management and API resource access
for communicating with VAST VMS clusters.
"""

from .base import (
    apiver,
    requisite,
    get_vms_session,
    instantiate_session_from_secret,
    CannotUseTrashAPI,
    RESTSession,
)

# Main session
from .vms_session import VmsSession

# Resources
from .resources import (
    VastResource,
    Version,
    Plugin,
    ViewPolicy,
    QosPolicy,
    Tenant,
    View,
    Folder,
    VipPool,
    Quota,
    Snapshot,
    GlobalSnapshotStream,
    User,
    Volume,
    BlockHost,
    BlockHostMapping,
    ProtectionPolicy,
    ProtectedPath,
    ReplicationPeers,
    Cluster,
)

# Iterator
from .iterator import ResourceIterator

# Test session
from .test_session import TestVmsSession

__all__ = [
    'apiver',
    'requisite',
    'get_vms_session',
    'instantiate_session_from_secret',
    'CannotUseTrashAPI',
    'RESTSession',
    'VmsSession',
    'TestVmsSession',
    'VastResource',
    'Version',
    'Plugin',
    'ViewPolicy',
    'QosPolicy',
    'Tenant',
    'View',
    'Folder',
    'VipPool',
    'Quota',
    'Snapshot',
    'GlobalSnapshotStream',
    'User',
    'Volume',
    'BlockHost',
    'BlockHostMapping',
    'ProtectionPolicy',
    'ProtectedPath',
    'ReplicationPeers',
    'Cluster',
    'ResourceIterator',
]
