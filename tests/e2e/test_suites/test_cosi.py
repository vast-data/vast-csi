"""COSI / vastcosi chart test bodies."""
import json
from tempfile import gettempdir

import pytest
from easypy.bunch import Bunch
from easypy.units import MINUTE
from plumbum.commands.processes import ProcessExecutionError
from e2e.builders.cosi import BucketAccessBuilder, BucketAccessClassBuilder, BucketClaimBuilder
from e2e.builders.workloads import PodBuilder
from e2e.constants import AWS_CLI_IMAGE
from e2e.logging import logger


@pytest.mark.e2e
@pytest.mark.cosi
def test_cosi(k8s):
    pod_name = "awscli-cosi-test"
    bucketclass_name = "vastdata-bucket"
    bucketaccessclass_name = "vastdata-bucket-access-class"
    bucketclaim_name = "vastdata-bucket-claim"
    bucket_access_name = "vastdata-bucket-access"
    secret_name = "test-cosi-secret"
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
    assert k8s.secrets.wait(30, name=secret_name)
    k8s.pods.create(
        PodBuilder.new(
            name=pod_name,
            container_name="awscli",
            image=AWS_CLI_IMAGE,
            command=["sleep"],
        )
        .with_args(["600"])
        .with_volume("cosi-secrets", "/data/cosi", {"name": "cosi-secrets", "secret": {"secretName": secret_name}})
    )
    k8s.pods.wait(
        name=pod_name, error_msg=f"the pod {pod_name!r} was not moved to the running state within the allotted period"
    )
    creds = Bunch.from_dict(json.loads(k8s.pods.exec(pod_name, "cat /data/cosi/BucketInfo")))
    assert (access_key := creds.spec.secretS3.accessKeyID)
    assert (secret_key := creds.spec.secretS3.accessSecretKey)
    assert (endpoint := creds.spec.secretS3.endpoint)
    assert (bucket := creds.spec.bucketName)
    k8s.pods.delete(name=pod_name)
    k8s.pods.create(
        PodBuilder.new(name=pod_name, container_name="awscli", image=AWS_CLI_IMAGE, command=["sleep"]).with_args(["600"])
    )
    k8s.pods.wait(
        name=pod_name, error_msg=f"the pod {pod_name!r} was not moved to the running state within the allotted period"
    )
    k8s.pods.exec(pod_name, f"/bin/sh -c 'echo test > {tmp_file}'")
    cli_base = f"AWS_REQUEST_CHECKSUM_CALCULATION=when_required AWS_ACCESS_KEY_ID={access_key} AWS_SECRET_ACCESS_KEY={secret_key} aws s3 --endpoint-url {endpoint} --no-verify-ssl"
    res = k8s.pods.exec(pod_name, f"/bin/sh -c '{cli_base} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "Completed 5 Bytes/5 Bytes" in res

    k8s.bucketclaims.delete(name=bucketclaim_name)
    with pytest.raises(ProcessExecutionError) as caught:
        k8s.pods.exec(pod_name, f"/bin/sh -c '{cli_base} cp {tmp_file} s3://{bucket}/cosi-test'")
    assert "An error occurred (InvalidAccessKeyId)" in caught.value.stderr
