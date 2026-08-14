"""COSI / vastcosi chart test bodies."""
import json
from tempfile import gettempdir

import pytest
from easypy.bunch import Bunch
from easypy.random import random_nice_name
from easypy.units import MINUTE
from plumbum.commands.processes import ProcessExecutionError
from lib.builders.cosi import BucketAccessBuilder, BucketAccessClassBuilder, BucketClaimBuilder
from lib.builders.workloads import PodBuilder
from lib.constants import AWS_CLI_IMAGE


def _awscli_pod(name, *, secret_name=None):
    builder = (
        PodBuilder.new(name=name, container_name="awscli", image=AWS_CLI_IMAGE, command=["sleep"])
        .with_args(["600"])
    )
    if secret_name:
        builder = builder.with_volume(
            "cosi-secrets",
            "/data/cosi",
            {"name": "cosi-secrets", "secret": {"secretName": secret_name}},
        )
    return builder


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi(system, k8s):
    suffix = random_nice_name(max_length=20)
    creds_pod = f"awscli-cosi-creds-{suffix}"
    cli_pod = f"awscli-cosi-{suffix}"
    bucketclass_name = "vastdata-bucket"
    bucketaccessclass_name = f"vastdata-bac-{suffix}"
    bucketclaim_name = f"vastdata-bc-{suffix}"
    bucket_access_name = f"vastdata-ba-{suffix}"
    secret_name = f"cosi-secret-{suffix}"
    tmp_file = f"{gettempdir()}/cosi_test"

    k8s.bucketaccessclasses.create(BucketAccessClassBuilder.new(name=bucketaccessclass_name))
    k8s.bucketclaims.create(BucketClaimBuilder.new(name=bucketclaim_name, bucket_class_name=bucketclass_name))
    k8s.bucketclaims.wait(timeout=MINUTE * 3, name=bucketclaim_name)
    k8s.bucketaccesses.create(
        BucketAccessBuilder.new(
            name=bucket_access_name,
            bucket_name=bucketclaim_name,
            bucket_access_class_name=bucketaccessclass_name,
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
    assert (access_key := creds.spec.secretS3.accessKeyID)
    assert (secret_key := creds.spec.secretS3.accessSecretKey)
    assert (endpoint := creds.spec.secretS3.endpoint)
    assert (bucket := creds.spec.bucketName)
    if system.clusters.is_loopback:
        endpoint = endpoint.replace(":80", ":9090")

    k8s.pods.delete(name=creds_pod, wait=False)
    k8s.pods.create(_awscli_pod(cli_pod))
    k8s.pods.wait(
        name=cli_pod,
        error_msg=f"the pod {cli_pod!r} was not moved to the running state within the allotted period",
    )
    k8s.pods.exec(cli_pod, f"/bin/sh -c 'echo test > {tmp_file}'")
    cli_base = (
        f"AWS_REQUEST_CHECKSUM_CALCULATION=when_required "
        f"AWS_ACCESS_KEY_ID={access_key} AWS_SECRET_ACCESS_KEY={secret_key} "
        f"aws s3 --endpoint-url {endpoint} --no-verify-ssl"
    )
    res = k8s.pods.exec(cli_pod, f"/bin/sh -c '{cli_base} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "Completed 5 Bytes/5 Bytes" in res

    # Revoke credentials via BucketAccess. The claim cannot finish deleting
    # while this object still holds bucketaccess-bucket-protection.
    k8s.bucketaccesses.delete(name=bucket_access_name, wait=False)
    k8s.bucketaccesses.wait(
        timeout=3 * MINUTE,
        name=bucket_access_name,
        condition="Deleted",
        error_msg=f"BucketAccess {bucket_access_name!r} was not deleted (keys not revoked)",
    )
    with pytest.raises(ProcessExecutionError) as caught:
        k8s.pods.exec(cli_pod, f"/bin/sh -c '{cli_base} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "An error occurred (InvalidAccessKeyId)" in caught.value.stderr

    k8s.bucketclaims.delete(name=bucketclaim_name, wait=False)
    k8s.bucketclaims.wait(
        timeout=3 * MINUTE,
        name=bucketclaim_name,
        condition="Deleted",
        error_msg=f"BucketClaim {bucketclaim_name!r} was not deleted after access was revoked",
    )
