"""NFS mTLS / vastcsi chart test bodies (separate suite from plain NFS)."""
import copy
from datetime import datetime

import pytest
from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.timing import wait
from easypy.units import MINUTE
from lib.builders.config import ConfigMapBuilder, SecretBuilder
from lib.builders.helm.csi import VastCsiHelmValuesBuilder
from lib.builders.storage import PVCBuilder, StorageClassBuilder
from lib.builders.workloads import StatefulSetBuilder
from lib.constants import CSI_NAMESPACE, ROOT_EXPORT, VIPPOOL_NAME
from lib.mtls import build_nfs_mtls_material, create_mgmt_secret_with_mtls

from e2e.logging import logger
from e2e.test_suites.common import parse_iso_date, read_in_pod

TLSHD_SIDECAR_MOUNT_PATH = "/etc/vast-tlshd"


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
def sidecar_tlshd(k8s, vast_mtls, request):
    """Force tlshd into csi-nfs-services using ConfigMap/Secret overrides."""
    suffix = random_nice_name(max_length=20)
    config_map_name = f"vast-nfs-tlshd-{suffix}"
    certificates_secret_name = f"vast-nfs-tlshd-certs-{suffix}"
    node_names = k8s.nodes.names()
    assert node_names, "No Kubernetes nodes found"

    k8s.nodes.ensure_nfs_mtls_host_stack(node_names)
    tlshd_conf = (
        "[authenticate]\n"
        "keyrings=vastcsi\n\n"
        "[authenticate.client]\n"
        f"x509.truststore={TLSHD_SIDECAR_MOUNT_PATH}/nfs-server-ca.pem\n"
    )
    k8s.apply([
        ConfigMapBuilder.new(name=config_map_name)
        .with_namespace(CSI_NAMESPACE)
        .with_data("tlshd.conf", tlshd_conf)
        .result(),
        SecretBuilder.new(name=certificates_secret_name)
        .with_namespace(CSI_NAMESPACE)
        .with_string_data("nfs-server-ca.pem", vast_mtls.server.ca_pem)
        .result(),
    ])

    chart = k8s.helmvalues.vastcsi
    original_values = copy.deepcopy(chart.memoized_values)

    def restore_host_and_chart():
        k8s.nodes.set_host_tlshd_running(True, node_names)
        failed = getattr(getattr(request.node, "rep_call", None), "failed", False)
        if failed:
            logger.notice(
                "Keeping tlshd sidecar ConfigMap/Secret and Helm overrides for debugging"
            )
            return
        chart.upgrade(original_values)
        k8s.kubectl(
            "delete", "configmap", config_map_name,
            "secret", certificates_secret_name,
            "-n", CSI_NAMESPACE, "--ignore-not-found",
        )

    request.addfinalizer(restore_host_and_chart)

    # Prove that the sidecar is sufficient: no host tlshd may service the mount.
    k8s.nodes.set_host_tlshd_running(False, node_names)
    overridden_values = (
        VastCsiHelmValuesBuilder(copy.deepcopy(original_values))
        .with_tlshd_overrides(
            config_map=config_map_name,
            certificates_secret=certificates_secret_name,
            mount_path=TLSHD_SIDECAR_MOUNT_PATH,
        )
        .result()
    )
    chart.upgrade(overridden_values)
    # Helm recreated the node pod; restart once more to install the host
    # mount.nfs wrapper used by this test environment.
    k8s.nodes.restart_csi_node_pods()

    pods = k8s.pods.get(
        labels={"app": "csi-vast-node"}, namespace=CSI_NAMESPACE,
    ) or []
    assert pods, "No csi-vast-node pods found"
    for pod in pods:
        pod_name = pod.metadata.name
        sidecar = next(
            container
            for container in pod.spec.containers
            if container.name == "csi-nfs-services"
        )
        # Entries sourced from valueFrom (e.g. X_CSI_NODE_ID) carry no "value".
        env = {item.name: item.get("value") for item in sidecar.get("env", [])}
        assert env.get("X_CSI_TLSHD_OVERRIDES") == "true"
        plugin = next(
            container
            for container in pod.spec.containers
            if container.name == "csi-vast-plugin"
        )
        plugin_env = {item.name: item.get("value") for item in plugin.get("env", [])}
        assert plugin_env.get("X_CSI_TLSHD_OVERRIDES") == "true"

        def tlshd_ready(pod_name=pod_name):
            rc, _, _ = k8s.kubectl[
                "exec", "-n", CSI_NAMESPACE, pod_name, "-c", "csi-nfs-services",
                "--", "sh", "-c",
                (
                    "grep -qx 'keyrings=vastcsi' /etc/tlshd.conf && "
                    f"test -s {TLSHD_SIDECAR_MOUNT_PATH}/nfs-server-ca.pem && "
                    "for comm in /proc/[0-9]*/comm; do "
                    "  [ \"$(cat \"$comm\")\" = tlshd ] && exit 0; "
                    "done; exit 1"
                ),
            ].run(retcode=None)
            return rc == 0

        wait(
            MINUTE,
            tlshd_ready,
            message=f"tlshd did not start in {pod_name!r}/csi-nfs-services",
        )

    yield


def _run_keyring_preflight(k8s, pod_name, *, keyring_name=None):
    """Run the sidecar's keyring preflight in-container, optionally on another ring.

    Returns the (rc, stdout, stderr) of a throwaway process, so a failing run
    leaves the running sidecar untouched.
    """
    rename = (
        f"mtls_utils.NFS_KEYRING_FALLBACK_NAME = {keyring_name!r}\n"
        if keyring_name
        else ""
    )
    code = (
        "import vast_csi.mtls_utils as mtls_utils\n"
        f"{rename}"
        "mtls_utils.ensure_nfs_keyring_id(wait_timeout=0)\n"
    )
    return k8s.kubectl[
        "exec", "-n", CSI_NAMESPACE, pod_name, "-c", "csi-nfs-services",
        "--", "/root/.venv/bin/python", "-c", code,
    ].run(retcode=None)


def _k8s_mtls_resources(k8s, request):
    """Yield names for one mTLS volume and drain it before its secret is removed."""
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


@pytest.fixture
def k8s_mtls(k8s, request):
    """Kubernetes objects for the host-tlshd mTLS test."""
    yield from _k8s_mtls_resources(k8s, request)


@pytest.fixture
def sidecar_k8s_mtls(sidecar_tlshd, k8s, request):
    """Kubernetes objects drained before the sidecar chart override is restored."""
    yield from _k8s_mtls_resources(k8s, request)


def _verify_mtls_volume(system, vast_mtls, k8s, resources):
    """Provision an mTLS volume, mount it, and verify application I/O."""
    create_mgmt_secret_with_mtls(
        k8s,
        name=resources.secret,
        system=system,
        client=vast_mtls.client,
        namespace=CSI_NAMESPACE,
    )

    k8s.storageclasses.create(
        StorageClassBuilder.new(
            name=resources.storage_class,
            vip_pool_name=VIPPOOL_NAME,
        )
        .with_root_export(ROOT_EXPORT)
        .with_view_policy(vast_mtls.policy_name)
        .with_mount_options("xprtsec=mtls")
        .with_vip_pool_fqdn_random_prefix(False)
        .with_secret(resources.secret)
    )

    k8s.pvcs.create(
        PVCBuilder.new(
            name=resources.pvc,
            access_modes=["ReadWriteOnce"],
            storage_class_name=resources.storage_class,
            storage="1Gi",
        )
    )
    k8s.pvcs.wait(
        timeout=3 * MINUTE,
        name=resources.pvc,
        error_msg=f"PVC {resources.pvc!r} did not bind under mTLS StorageClass",
    )

    k8s.sts.create(
        StatefulSetBuilder.new(name=resources.sts, pvc=resources.pvc, replicas=1)
    )
    pod_name = f"{resources.sts}-0"
    k8s.pods.wait(
        timeout=5 * MINUTE,
        name=pod_name,
        error_msg=(
            f"Pod {pod_name!r} did not start with NFS mTLS "
            f"(check node tlshd, VAST NFS client, and CSI logs)"
        ),
    )

    date = wait(
        MINUTE,
        lambda: read_in_pod(k8s, pod_name, f"/shared/{pod_name}"),
        message=f"pod {pod_name!r} wrote nothing to its mTLS volume",
    )
    assert isinstance(parse_iso_date(date), datetime)
    logger.info(
        f"NFS mTLS mount verified on {pod_name!r} "
        f"(policy={vast_mtls.policy_name!r})"
    )


@pytest.mark.e2e
@pytest.mark.mtls
def test_nfs_mtls_basic(system, vast_mtls, k8s, k8s_mtls):
    """End-to-end NFS mTLS mount using per-volume client certs in the SC secret.

      1. Put client cert/key into a StorageClass secret as ``mtls_client_*``
      2. Point host ``tlshd`` truststore at the server CA (privileged per-node pods)
      3. StorageClass with ``xprtsec=mtls`` + the mTLS view policy from ``vast_mtls``
      4. Mount a PVC through it and verify IO

    Requires VAST 5.5+, worker nodes with VAST NFS client + ktls/tlshd
    """
    node_names = k8s.nodes.names()
    assert node_names, "No Kubernetes nodes found"

    k8s.nodes.ensure_nfs_mtls_host_stack(node_names)
    k8s.nodes.configure_tlshd_truststore(vast_mtls.server.ca_pem, node_names)
    k8s.nodes.restart_csi_node_pods()

    _verify_mtls_volume(system, vast_mtls, k8s, k8s_mtls)


@pytest.mark.e2e
@pytest.mark.mtls
def test_nfs_mtls_with_tlshd_sidecar(
    system,
    vast_mtls,
    k8s,
    sidecar_k8s_mtls,
):
    """Mount with host tlshd stopped and ConfigMap/Secret-backed sidecar tlshd."""
    _verify_mtls_volume(system, vast_mtls, k8s, sidecar_k8s_mtls)


@pytest.mark.e2e
@pytest.mark.mtls
def test_nfs_keyring_creation_failure_is_fatal(k8s, sidecar_tlshd):
    """The sidecar must refuse to start tlshd when the cert keyring is unusable.

    Leading-dot keyring names are reserved for the kernel, so ``keyctl newring``
    returns EPERM for them. That produces a real creation failure to drive the
    preflight with, rather than a simulated one. The sidecar runs with tlshd
    overrides here, so the preflight looks only at the ``vastcsi`` ring and
    cannot fall back to a kernel ``.nfs`` ring that already exists on the node.
    """
    pods = k8s.pods.get(
        labels={"app": "csi-vast-node"}, namespace=CSI_NAMESPACE,
    ) or []
    assert pods, "No csi-vast-node pods found"
    pod_name = pods[0].metadata.name

    rc, _, stderr = _run_keyring_preflight(
        k8s, pod_name, keyring_name=".vastcsi-e2e",
    )
    assert rc != 0, (
        "sidecar preflight started tlshd despite being unable to create the "
        "NFS keyring; mTLS mounts would fail later with no obvious cause"
    )
    assert "keyctl" in stderr and "newring" in stderr, (
        f"preflight failed without the expected keyctl newring error: {stderr!r}"
    )

    rc, _, stderr = _run_keyring_preflight(k8s, pod_name)
    assert rc == 0, (
        f"preflight failed with the real keyring name: {stderr!r}"
    )
