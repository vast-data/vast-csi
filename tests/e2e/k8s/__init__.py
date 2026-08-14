"""
Kubernetes resource managers for CSI tests.

Import the K8S facade and individual resource classes from here.
"""
from e2e.k8s._base import K8S, KubernetesResource, WaitResourceFailed
from e2e.k8s.secret import Secret
from e2e.k8s.workloads import Deployment, Namespace, Pod, StatefulSet
from e2e.k8s.storage import (
    PersistentVolumeClaim,
    PersistentVolume,
    StorageClass,
    VolumeSnapshot,
    VolumeSnapshotContent,
)
from e2e.k8s.helm import HelmValues
from e2e.k8s.cosi import BucketAccess, BucketAccessClass, BucketClaim
from e2e.k8s.vast import VastCSIDriver, VastCluster, VastStorage
from e2e.k8s.replication import VastVolumeReplication, VastStorageClassReplication, VastReplicationContent
from e2e.k8s.resource_sampler import ResourceSampler

__all__ = [
    "K8S",
    "KubernetesResource",
    "WaitResourceFailed",
    "Secret",
    "Deployment",
    "Namespace",
    "Pod",
    "StatefulSet",
    "PersistentVolumeClaim",
    "PersistentVolume",
    "StorageClass",
    "VolumeSnapshot",
    "VolumeSnapshotContent",
    "HelmValues",
    "BucketAccess",
    "BucketAccessClass",
    "BucketClaim",
    "VastCSIDriver",
    "VastCluster",
    "VastStorage",
    "VastVolumeReplication",
    "VastStorageClassReplication",
    "VastReplicationContent",
    "ResourceSampler",
]
