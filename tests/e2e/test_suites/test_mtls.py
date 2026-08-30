"""NFS mTLS / vastcsi chart test bodies (separate suite from plain NFS)."""
from datetime import datetime

import pytest
from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.timing import wait
from easypy.units import MINUTE

from lib.builders.storage import PVCBuilder, StorageClassBuilder
from lib.builders.workloads import StatefulSetBuilder
from lib.constants import CSI_NAMESPACE, ROOT_EXPORT, VIPPOOL_NAME
from lib.mtls import build_nfs_mtls_material, create_mgmt_secret_with_mtls
from e2e.logging import logger
from e2e.test_suites.common import parse_iso_date, read_in_pod


@pytest.fixture
def vast_mtls(system, request):
    """VAST-side mTLS material: server cert, tenant client CA and a dedicated view policy.

    Requested before ``k8s`` so this teardown runs *after* the k8s cleanup: the
    view policy cannot be dropped while CSI views still reference it.
    """
    vip_ips = system.vippools.list_ips(VIPPOOL_NAME)
    assert vip_ips, f"VIP pool {VIPPOOL_NAME!r} has no IPs"

    server, client = build_nfs_mtls_material(vip_ips)
    system.clusters.ensure_nfs_server_tls(
        certificate_pem=server.certificate_pem,
        private_key_pem=server.private_key_pem,
    )

    tenant_id = system.viewpolicies.default_tenant_id()
    policy_name = f"csi-e2e-mtls-{random_nice_name(max_length=20)}"
    policy = system.viewpolicies.create_mtls(policy_name, tenant_id=tenant_id)
    tls_cert = system.tlscertificates.upload_nfs_ca(tenant_id=tenant_id, ca_pem=client.ca_pem)

    yield Bunch(server=server, client=client, policy_name=policy_name)

    if getattr(getattr(request.node, "rep_call", None), "failed", False):
        logger.notice(
            f"Skipping VMS cleanup after failure (kept view policy {policy_name!r}, "
            f"tlscertificate {tls_cert.id})"
        )
        return
    system.tlscertificates.delete_by_id(tls_cert.id)
    system.viewpolicies.delete_by_id(policy.id)


@pytest.fixture
def k8s_mtls(k8s, request):
    """Kubernetes objects for this mTLS volume (secret, StorageClass, PVC, STS).

    Also drains the CSI volume in order. Requested after ``k8s`` so this runs
    *before* the generic creation-recorder cleanup. ``DeleteVolume`` needs the
    volume detached and the per-test mgmt secret still present, but the recorder
    deletes StatefulSets, PVCs and secrets in parallel — leaving the VAST view
    (and so the view policy) undeletable.
    """
    suffix = random_nice_name(max_length=20)
    resources = Bunch(
        secret=f"vast-mgmt-mtls-{suffix}",
        storage_class=f"vastdata-filesystem-mtls-{suffix}",
        pvc=f"pvc-mtls-{suffix}",
        sts=f"sts-mtls-{suffix}",
    )
    yield resources

    if getattr(getattr(request.node, "rep_call", None), "failed", False):
        return  # k8s fixture preserves the whole set for debugging

    pv_name = k8s.pvcs.get(name=resources.pvc).spec.volumeName
    k8s.sts.delete(name=resources.sts)
    k8s.pods.wait(name=f"{resources.sts}-0", condition="Deleted", timeout=2 * MINUTE)
    k8s.pvcs.delete(name=resources.pvc)
    k8s.pvs.wait(
        name=pv_name,
        condition="Deleted",
        timeout=3 * MINUTE,
        error_msg=f"CSI did not delete {pv_name!r}; its VAST view would leak",
    )


@pytest.mark.e2e
@pytest.mark.mtls
@pytest.mark.nfs
def test_nfs_mtls_basic(system, vast_mtls, k8s, k8s_mtls):
    """End-to-end NFS mTLS mount using per-volume client certs in the SC secret.

      1. Put client cert/key into a StorageClass secret as ``mtls_client_*``
      2. Point host ``tlshd`` truststore at the server CA (privileged per-node pods)
      3. StorageClass with ``xprtsec=mtls`` + the mTLS view policy from ``vast_mtls``
      4. Mount a PVC through it and verify IO

    Requires VAST 5.5+, worker nodes with VAST NFS client + ktls/tlshd
    """
    create_mgmt_secret_with_mtls(
        k8s, name=k8s_mtls.secret, system=system, client=vast_mtls.client, namespace=CSI_NAMESPACE,
    )

    node_names = k8s.nodes.names()
    assert node_names, "No Kubernetes nodes found"
    # Prefer VAST NFS from VM cloud-init; this is idempotent if already installed.
    k8s.nodes.ensure_nfs_mtls_host_stack(node_names)
    k8s.nodes.configure_tlshd_truststore(vast_mtls.server.ca_pem, node_names)
    # Restart reloads tlshd.conf into csi-nfs-services and re-wraps mount.nfs
    # onto the host binary (CSI image nfs-utils is too old for xprtsec).
    k8s.nodes.restart_csi_node_pods()

    k8s.storageclasses.create(
        StorageClassBuilder.new(name=k8s_mtls.storage_class, vip_pool_name=VIPPOOL_NAME)
        .with_root_export(ROOT_EXPORT)
        .with_view_policy(vast_mtls.policy_name)
        .with_mount_options("xprtsec=mtls")
        .with_vip_pool_fqdn_random_prefix(False)
        .with_secret(k8s_mtls.secret)
    )

    k8s.pvcs.create(
        PVCBuilder.new(
            name=k8s_mtls.pvc,
            access_modes=["ReadWriteOnce"],
            storage_class_name=k8s_mtls.storage_class,
            storage="1Gi",
        )
    )
    k8s.pvcs.wait(
        timeout=3 * MINUTE,
        name=k8s_mtls.pvc,
        error_msg=f"PVC {k8s_mtls.pvc!r} did not bind under mTLS StorageClass",
    )

    k8s.sts.create(StatefulSetBuilder.new(name=k8s_mtls.sts, pvc=k8s_mtls.pvc, replicas=1))
    pod_name = f"{k8s_mtls.sts}-0"
    k8s.pods.wait(
        timeout=5 * MINUTE,
        name=pod_name,
        error_msg=(
            f"Pod {pod_name!r} did not start with NFS mTLS "
            f"(check node tlshd, VAST NFS client, and CSI logs)"
        ),
    )

    # The pod appends a timestamp once a second, so it is Running for a moment
    # before the first line lands on the mTLS mount.
    date = wait(
        MINUTE,
        lambda: read_in_pod(k8s, pod_name, f"/shared/{pod_name}"),
        message=f"pod {pod_name!r} wrote nothing to its mTLS volume",
    )
    dt = parse_iso_date(date)
    assert isinstance(dt, datetime)
    logger.info(f"NFS mTLS mount verified on {pod_name!r} (policy={vast_mtls.policy_name!r})")
