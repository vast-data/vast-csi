"""COSI / vastcosi chart test bodies."""
from __future__ import annotations

import base64
import json
from tempfile import gettempdir

import pytest
from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.semver import SemVer
from easypy.timing import wait
from easypy.units import MINUTE, GiB
from plumbum.commands.processes import ProcessExecutionError

from lib.builders.cosi import (
    BucketAccessBuilder,
    BucketAccessClassBuilder,
    BucketClaimBuilder,
    BucketClassBuilder,
)
from lib.builders.workloads import PodBuilder
from lib.constants import AWS_CLI_IMAGE, S3_POLICY_NAME, VIPPOOL_NAME

DEFAULT_BUCKET_CLASS = "vastdata-bucket"
COSI_ROOT_EXPORT = "/buckets"


def _awscli_pod(name, *, secret_name=None, flat_name=None):
    builder = (
        PodBuilder.new(name=name, container_name="awscli", image=AWS_CLI_IMAGE, command=["sleep"])
        .with_args(["600"])
    )
    if flat_name:
        builder = builder.with_env_from(secret_name=flat_name, config_map_name=flat_name)
    elif secret_name:
        builder = builder.with_volume(
            "cosi-secrets",
            "/data/cosi",
            {"name": "cosi-secrets", "secret": {"secretName": secret_name}},
        )
    return builder


def _loopback_endpoint(system, endpoint: str) -> str:
    if system.clusters.is_loopback:
        return endpoint.replace(":80", ":9090")
    return endpoint


def _aws_cli(access_key: str, secret_key: str, endpoint: str) -> str:
    return (
        f"AWS_REQUEST_CHECKSUM_CALCULATION=when_required "
        f"AWS_ACCESS_KEY_ID={access_key} AWS_SECRET_ACCESS_KEY={secret_key} "
        f"aws s3 --endpoint-url {endpoint} --no-verify-ssl"
    )


def _grant_and_read_bucketinfo(k8s, system, *, claim_name: str, suffix: str):
    """Create BAC+BA, wait for Secret, return (creds Bunch, secret_name, bac_name, ba_name)."""
    bac_name = f"vastdata-bac-{suffix}"
    ba_name = f"vastdata-ba-{suffix}"
    secret_name = f"cosi-secret-{suffix}"
    creds_pod = f"awscli-cosi-creds-{suffix}"

    k8s.bucketaccessclasses.create(BucketAccessClassBuilder.new(name=bac_name))
    k8s.bucketaccesses.create(
        BucketAccessBuilder.new(
            name=ba_name,
            bucket_name=claim_name,
            bucket_access_class_name=bac_name,
            secret_name=secret_name,
        )
    )
    assert k8s.secrets.wait(MINUTE, name=secret_name)

    k8s.pods.create(_awscli_pod(creds_pod, secret_name=secret_name))
    k8s.pods.wait(
        name=creds_pod,
        error_msg=f"the pod {creds_pod!r} was not moved to the running state within the allotted period",
    )
    creds = Bunch.from_dict(json.loads(k8s.pods.exec(creds_pod, "cat /data/cosi/BucketInfo")))
    k8s.pods.delete(name=creds_pod, wait=False)

    assert creds.spec.secretS3.accessKeyID
    assert creds.spec.secretS3.accessSecretKey
    assert creds.spec.secretS3.endpoint
    assert creds.spec.bucketName
    creds.spec.secretS3.endpoint = _loopback_endpoint(system, creds.spec.secretS3.endpoint)
    return creds, secret_name, bac_name, ba_name


def _revoke_access(k8s, ba_name: str):
    k8s.bucketaccesses.delete(name=ba_name, wait=False)
    k8s.bucketaccesses.wait(
        timeout=3 * MINUTE,
        name=ba_name,
        condition="Deleted",
        error_msg=f"BucketAccess {ba_name!r} was not deleted (keys not revoked)",
    )


def _delete_claim(k8s, claim_name: str):
    k8s.bucketclaims.delete(name=claim_name, wait=False)
    k8s.bucketclaims.wait(
        timeout=3 * MINUTE,
        name=claim_name,
        condition="Deleted",
        error_msg=f"BucketClaim {claim_name!r} was not deleted",
    )


def _s3_put_ok(k8s, pod_name: str, cli: str, bucket: str, tmp_file: str):
    k8s.pods.exec(pod_name, f"/bin/sh -c 'echo test > {tmp_file}'")
    res = k8s.pods.exec(pod_name, f"/bin/sh -c '{cli} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "Completed 5 Bytes/5 Bytes" in res


def _secret_data(k8s, name: str, namespace: str = "default") -> dict[str, str]:
    sec = k8s.secrets.get(name=name, namespace=namespace)
    assert sec, f"Secret {name!r} not found"
    out = {}
    for key, value in (sec.data or {}).items():
        out[key] = base64.b64decode(value).decode()
    return out


def _configmap_data(k8s, name: str, namespace: str = "default") -> dict[str, str]:
    cm = k8s.resource("configmap").get(name=name, namespace=namespace)
    assert cm, f"ConfigMap {name!r} not found"
    return dict(cm.data or {})


def _default_bucketclass_params(**extra) -> dict:
    params = {
        "root_export": COSI_ROOT_EXPORT,
        "vip_pool_name": VIPPOOL_NAME,
        "view_policy": S3_POLICY_NAME,
        "scheme": "http",
    }
    params.update(extra)
    return params


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi(system, k8s):
    suffix = random_nice_name(max_length=20)
    cli_pod = f"awscli-cosi-{suffix}"
    bucketclaim_name = f"vastdata-bc-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_test"

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=bucketclaim_name, bucket_class_name=DEFAULT_BUCKET_CLASS)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=bucketclaim_name)

    creds, _, _, ba_name = _grant_and_read_bucketinfo(
        k8s, system, claim_name=bucketclaim_name, suffix=suffix
    )
    access_key = creds.spec.secretS3.accessKeyID
    secret_key = creds.spec.secretS3.accessSecretKey
    endpoint = creds.spec.secretS3.endpoint
    bucket = creds.spec.bucketName

    k8s.pods.create(_awscli_pod(cli_pod))
    k8s.pods.wait(
        name=cli_pod,
        error_msg=f"the pod {cli_pod!r} was not moved to the running state within the allotted period",
    )
    cli = _aws_cli(access_key, secret_key, endpoint)
    _s3_put_ok(k8s, cli_pod, cli, bucket, tmp_file)

    _revoke_access(k8s, ba_name)
    with pytest.raises(ProcessExecutionError) as caught:
        k8s.pods.exec(cli_pod, f"/bin/sh -c '{cli} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "An error occurred (InvalidAccessKeyId)" in caught.value.stderr

    _delete_claim(k8s, bucketclaim_name)


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi_flat_credentials(system, k8s):
    """Annotated BucketAccess yields sibling *-flat Secret/ConfigMap (VCSI-447)."""
    suffix = random_nice_name(max_length=20)
    claim_name = f"vastdata-bc-flat-{suffix}"
    bac_name = f"vastdata-bac-flat-{suffix}"
    ba_name = f"vastdata-ba-flat-{suffix}"
    secret_name = f"cosi-secret-flat-{suffix}"
    flat_name = f"{secret_name}-flat"
    cli_pod = f"awscli-cosi-flat-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_flat_test"

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=claim_name, bucket_class_name=DEFAULT_BUCKET_CLASS)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=claim_name)

    k8s.bucketaccessclasses.create(BucketAccessClassBuilder.new(name=bac_name))
    k8s.bucketaccesses.create(
        BucketAccessBuilder.new(
            name=ba_name,
            bucket_name=claim_name,
            bucket_access_class_name=bac_name,
            secret_name=secret_name,
        ).with_flatten_credentials()
    )
    assert k8s.secrets.wait(MINUTE, name=secret_name)
    wait(
        2 * MINUTE,
        lambda: bool(k8s.secrets.get(name=flat_name)),
        message=f"flat Secret {flat_name!r} was not created",
    )
    wait(
        MINUTE,
        lambda: bool(k8s.resource("configmap").get(name=flat_name)),
        message=f"flat ConfigMap {flat_name!r} was not created",
    )

    sec = _secret_data(k8s, flat_name)
    cm = _configmap_data(k8s, flat_name)
    assert sec["AWS_ACCESS_KEY_ID"]
    assert sec["AWS_SECRET_ACCESS_KEY"]
    assert cm["BUCKET_NAME"]
    assert cm["BUCKET_ENDPOINT"]

    endpoint = _loopback_endpoint(system, cm["BUCKET_ENDPOINT"])
    k8s.pods.create(_awscli_pod(cli_pod, flat_name=flat_name))
    k8s.pods.wait(name=cli_pod)
    # Override endpoint for loopback S3 port after envFrom.
    cli = (
        f"AWS_REQUEST_CHECKSUM_CALCULATION=when_required "
        f"aws s3 --endpoint-url {endpoint} --no-verify-ssl"
    )
    _s3_put_ok(k8s, cli_pod, cli, cm["BUCKET_NAME"], tmp_file)

    _revoke_access(k8s, ba_name)
    _delete_claim(k8s, claim_name)


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi_claim_max_size(system, k8s):
    """Claim annotation cosi.vastdata.com/maxSize creates a VMS path quota (VCSI-499)."""
    suffix = random_nice_name(max_length=20)
    claim_name = f"vastdata-bc-quota-{suffix}"
    max_size = "5Gi"
    expected_bytes = int(5 * GiB)

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=claim_name, bucket_class_name=DEFAULT_BUCKET_CLASS)
        .with_max_size(max_size)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=claim_name)

    creds, _, _, ba_name = _grant_and_read_bucketinfo(
        k8s, system, claim_name=claim_name, suffix=f"quota-{suffix}"
    )
    bucket = creds.spec.bucketName
    view_path = f"{COSI_ROOT_EXPORT.rstrip('/')}/{bucket}"

    def _quota():
        return system.quotas.one(path=view_path, fail_if_missing=False)

    wait(2 * MINUTE, lambda: _quota() is not None, message=f"quota missing for {view_path}")
    quota = _quota()
    assert int(quota.hard_limit) == expected_bytes, (
        f"expected hard_limit={expected_bytes}, got {quota.hard_limit}"
    )

    _revoke_access(k8s, ba_name)
    _delete_claim(k8s, claim_name)
    wait(
        2 * MINUTE,
        lambda: system.quotas.one(path=view_path, fail_if_missing=False) is None,
        message=f"quota for {view_path} was not deleted with the claim",
    )


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi_lifecycle_rules(system, k8s):
    """BucketClass lifecycle_rules applied at create (VCSI-327)."""
    suffix = random_nice_name(max_length=20)
    # COSI bucket name = BucketClass name + claim UID (36); class name must be ≤27.
    bc_name = f"vbc-lc-{suffix}"
    claim_name = f"vastdata-claim-lc-{suffix}"
    cli_pod = f"awscli-cosi-lc-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_lc_test"

    k8s.bucketclasses.create(
        BucketClassBuilder.new(name=bc_name, **_default_bucketclass_params())
        .with_lifecycle_rules([
            {"name": "expire-logs", "expiration_days": 30, "prefix": "logs/"},
            {
                "name": "expire-tmp",
                "expiration_days": 7,
                "prefix": "tmp/",
                "abort_mpu_days_after_initiation": 1,
            },
        ])
    )
    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=claim_name, bucket_class_name=bc_name)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=claim_name)

    creds, _, _, ba_name = _grant_and_read_bucketinfo(
        k8s, system, claim_name=claim_name, suffix=f"lc-{suffix}"
    )
    access_key = creds.spec.secretS3.accessKeyID
    secret_key = creds.spec.secretS3.accessSecretKey
    endpoint = creds.spec.secretS3.endpoint
    bucket = creds.spec.bucketName

    k8s.pods.create(_awscli_pod(cli_pod))
    k8s.pods.wait(name=cli_pod)
    s3api = (
        f"AWS_REQUEST_CHECKSUM_CALCULATION=when_required "
        f"AWS_ACCESS_KEY_ID={access_key} AWS_SECRET_ACCESS_KEY={secret_key} "
        f"aws s3api --endpoint-url {endpoint} --no-verify-ssl"
    )

    def _lifecycle_json():
        try:
            out = k8s.pods.exec(
                cli_pod,
                f"/bin/sh -c '{s3api} get-bucket-lifecycle-configuration --bucket {bucket}'",
            )
            return json.loads(out)
        except ProcessExecutionError:
            return None

    wait(
        2 * MINUTE,
        lambda: bool(_lifecycle_json() and _lifecycle_json().get("Rules")),
        message="S3 lifecycle configuration was not applied on the bucket",
    )
    rules = _lifecycle_json()["Rules"]
    rule_ids = {r.get("ID") for r in rules}
    assert "expire-logs" in rule_ids
    assert "expire-tmp" in rule_ids

    cli = _aws_cli(access_key, secret_key, endpoint)
    _s3_put_ok(k8s, cli_pod, cli, bucket, tmp_file)

    _revoke_access(k8s, ba_name)
    _delete_claim(k8s, claim_name)
    k8s.bucketclasses.delete(name=bc_name, namespace=None, wait=False)


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi_bucket_clone(system, k8s):
    """Writable clone via cosi.vastdata.com/sourceBucket (VCSI-325)."""
    suffix = random_nice_name(max_length=20)
    src_claim = f"vastdata-bc-src-{suffix}"
    clone_claim = f"vastdata-bc-clone-{suffix}"
    cli_pod = f"awscli-cosi-clone-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_clone_test"

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=src_claim, bucket_class_name=DEFAULT_BUCKET_CLASS)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=src_claim)
    src_creds, _, _, src_ba = _grant_and_read_bucketinfo(
        k8s, system, claim_name=src_claim, suffix=f"src-{suffix}"
    )
    source_bucket = src_creds.spec.bucketName

    # Seed an object on the source before cloning.
    k8s.pods.create(_awscli_pod(cli_pod))
    k8s.pods.wait(name=cli_pod)
    src_cli = _aws_cli(
        src_creds.spec.secretS3.accessKeyID,
        src_creds.spec.secretS3.accessSecretKey,
        src_creds.spec.secretS3.endpoint,
    )
    k8s.pods.exec(cli_pod, f"/bin/sh -c 'echo source-data > {tmp_file}'")
    res = k8s.pods.exec(
        cli_pod, f"/bin/sh -c '{src_cli} cp {tmp_file} s3://{source_bucket}/from-source'"
    )
    assert "Completed" in res

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=clone_claim, bucket_class_name=DEFAULT_BUCKET_CLASS)
        .with_source_bucket(source_bucket, blocking=True)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 5, name=clone_claim)

    clone_creds, _, _, clone_ba = _grant_and_read_bucketinfo(
        k8s, system, claim_name=clone_claim, suffix=f"clone-{suffix}"
    )
    clone_bucket = clone_creds.spec.bucketName
    assert clone_bucket != source_bucket

    clone_cli = _aws_cli(
        clone_creds.spec.secretS3.accessKeyID,
        clone_creds.spec.secretS3.accessSecretKey,
        clone_creds.spec.secretS3.endpoint,
    )
    listed = k8s.pods.exec(
        cli_pod, f"/bin/sh -c '{clone_cli} ls s3://{clone_bucket}/'"
    )
    assert "from-source" in listed
    _s3_put_ok(k8s, cli_pod, clone_cli, clone_bucket, tmp_file)

    _revoke_access(k8s, clone_ba)
    _delete_claim(k8s, clone_claim)
    _revoke_access(k8s, src_ba)
    _delete_claim(k8s, src_claim)


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi_force_credentials(system, k8s):
    """BucketAccessClass credentialsSecretName installs forced S3 keys (VCSI-326)."""
    sw = system.versions.get_sw_version()
    if sw < SemVer.loads_fuzzy("5.4"):
        pytest.skip(f"force credentials require VAST >= 5.4 (got {sw})")

    suffix = random_nice_name(max_length=20)
    claim_name = f"vastdata-bc-force-{suffix}"
    bac_name = f"vastdata-bac-force-{suffix}"
    ba_name = f"vastdata-ba-force-{suffix}"
    out_secret = f"cosi-secret-force-{suffix}"
    input_secret = f"vault-s3-keys-{suffix}"
    cli_pod = f"awscli-cosi-force-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_force_test"

    access_key = "VCSI326FORCEKEY00001"
    secret_key = "vcsi326forcekeabcdefghijklmnopqrstuvwxyz"
    k8s.secrets.create(
        "default",
        name=input_secret,
        accessKeyID=access_key,
        accessSecretKey=secret_key,
    )

    k8s.bucketclaims.create(
        BucketClaimBuilder.new(name=claim_name, bucket_class_name=DEFAULT_BUCKET_CLASS)
    )
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=claim_name)

    k8s.bucketaccessclasses.create(
        BucketAccessClassBuilder.new(name=bac_name)
        .with_credentials_secret(input_secret, namespace="default")
    )
    k8s.bucketaccesses.create(
        BucketAccessBuilder.new(
            name=ba_name,
            bucket_name=claim_name,
            bucket_access_class_name=bac_name,
            secret_name=out_secret,
        )
    )
    assert k8s.secrets.wait(MINUTE, name=out_secret)

    creds_pod = f"awscli-cosi-force-creds-{suffix}"
    k8s.pods.create(_awscli_pod(creds_pod, secret_name=out_secret))
    k8s.pods.wait(name=creds_pod)
    creds = Bunch.from_dict(json.loads(k8s.pods.exec(creds_pod, "cat /data/cosi/BucketInfo")))
    k8s.pods.delete(name=creds_pod, wait=False)

    assert creds.spec.secretS3.accessKeyID == access_key
    assert creds.spec.secretS3.accessSecretKey == secret_key
    endpoint = _loopback_endpoint(system, creds.spec.secretS3.endpoint)
    bucket = creds.spec.bucketName

    k8s.pods.create(_awscli_pod(cli_pod))
    k8s.pods.wait(name=cli_pod)
    cli = _aws_cli(access_key, secret_key, endpoint)
    _s3_put_ok(k8s, cli_pod, cli, bucket, tmp_file)

    _revoke_access(k8s, ba_name)
    _delete_claim(k8s, claim_name)
