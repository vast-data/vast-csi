"""
Kubernetes resource managers for CSI tests.

Import the K8S facade and factory from here.
"""
from lib.k8s._base import K8S
from lib.k8s.factory import make_k8s

__all__ = [
    "K8S",
    "make_k8s",
]
