"""
Kubernetes resource managers for CSI tests.

Import the K8S facade and individual resource classes from here.
"""
from lib.k8s._base import K8S, KubernetesResource, WaitResourceFailed
from lib.k8s.factory import make_k8s
from lib.k8s.secret import Secret
from lib.k8s.node import Node
from lib.k8s.workloads import Deployment, Namespace, Pod, StatefulSet
from lib.k8s.storage import (
    PersistentVolumeClaim,
    PersistentVolume,
    StorageClass,
    VolumeSnapshot,
    VolumeSnapshotContent,
)
from lib.k8s.helm import HelmValues
from lib.k8s.cosi import BucketAccess, BucketAccessClass, BucketClaim
from lib.k8s.vast import VastCSIDriver, VastCluster, VastStorage
from lib.k8s.replication import VastVolumeReplication, VastStorageClassReplication, VastReplicationContent
from lib.k8s.resource_sampler import ResourceSampler

__all__ = [
    "K8S",
    "make_k8s",
    "KubernetesResource",
    "WaitResourceFailed",
    "Secret",
    "Node",
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
