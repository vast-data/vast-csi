"""Construct a K8S client from kubectl/oc and optional helm."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from plumbum import local

from lib.k8s._base import K8S


def make_k8s(
    *,
    kubeconfig: str | Path | None = None,
    kubectl: str | None = None,
    helm: str | bool | None = None,
) -> K8S:
    """Return a ``K8S`` facade.

    *kubectl*: binary name or path (default: ``E2E_KUBECTL``, then ``oc``, then ``kubectl``).
    *helm*: ``True`` to require helm on PATH, a binary path, or ``None`` to skip helm.
    """
    kubeconfig = kubeconfig or os.environ.get("KUBECONFIG")
    exe = kubectl or os.environ.get("E2E_KUBECTL") or (shutil.which("oc") and "oc") or "kubectl"
    cmd = local[exe]
    if kubeconfig:
        cmd = cmd.with_env(KUBECONFIG=str(kubeconfig))

    helm_cmd = None
    if helm is True:
        helm_path = shutil.which("helm")
        if not helm_path:
            raise RuntimeError("helm is required")
        helm_cmd = local[helm_path]
        if kubeconfig:
            helm_cmd = helm_cmd.with_env(KUBECONFIG=str(kubeconfig))
    elif isinstance(helm, str):
        helm_cmd = local[helm]
        if kubeconfig:
            helm_cmd = helm_cmd.with_env(KUBECONFIG=str(kubeconfig))

    return K8S(kube_cmd=cmd, helm_cmd=helm_cmd)
