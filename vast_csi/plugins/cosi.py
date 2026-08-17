# Copyright 2024 VAST Data Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from dataclasses import dataclass

import grpc
from vast_csi.proto import cosi_pb2_grpc as cosi_grpc
from vast_csi import csi_types as types
from vast_csi.builders.cosi import (
    apply_bucket_post_provision,
    build_bucket_endpoint_id,
    cosi_clone_snap_name,
    cosi_clone_stream_name,
    parse_create_bucket_params,
    provision_bucket_view,
)
from vast_csi.csi_types import GRPC_TO_CSI, INTERNAL, INVALID_ARGUMENT
from vast_csi.exceptions import Abort
from vast_csi.extensions_client import resolve_cosi_bucket_auth, resolve_secret
from vast_csi.plugins.base import Instrumented
from vast_csi.configuration import Config
from vast_csi.cosi_credentials import grant_bucket_access, revoke_bucket_access


CONF = None

SECRET_NAME_PARAM = "vastdata.com/secret-name"
SECRET_NAMESPACE_PARAM = "vastdata.com/secret-namespace"


def _abort_from_rpc(exc: grpc.RpcError) -> Abort:
    code = GRPC_TO_CSI.get(exc.code(), INTERNAL)
    return Abort(code, exc.details() or str(exc))


@dataclass(frozen=True)
class BucketId:
    """COSI bucket_id: name@tenant@endpoint."""

    name: str
    tenant_id: str
    endpoint: str

    @classmethod
    def parse(cls, bucket_id: str) -> "BucketId":
        parts = bucket_id.split("@", 2)
        if len(parts) != 3:
            raise Abort(INVALID_ARGUMENT, f"invalid bucket_id format: {bucket_id!r}")
        return cls(parts[0], parts[1], parts[2])


class CosiIdentity(cosi_grpc.IdentityServicer, Instrumented):

    def DriverGetInfo(self, request, context):
        return types.DriverGetInfoResp(name=CONF.plugin_name)


class CosiProvisioner(cosi_grpc.ProvisionerServicer, Instrumented):

    def resolve_secrets(self, params):
        # Prefer secret refs from parameters (cheaper ResolveSecret) when present —
        # DeleteBucket can carry both bucket_id and parameters. Fall back to
        # ResolveCOSIBucketAuth(bucket_id) when refs are absent (grant/revoke, or
        # legacy buckets without secret params → empty → /opt/vms-auth).
        parameters = params.get("parameters") or {}
        secret_name = parameters.get(SECRET_NAME_PARAM)
        secret_namespace = parameters.get(SECRET_NAMESPACE_PARAM)
        if secret_name or secret_namespace:
            if not secret_name or not secret_namespace:
                raise Abort(
                    INVALID_ARGUMENT,
                    f"{SECRET_NAME_PARAM} and {SECRET_NAMESPACE_PARAM} must both be set",
                )
            try:
                return resolve_secret(secret_name, secret_namespace)
            except grpc.RpcError as exc:
                raise _abort_from_rpc(exc) from exc

        if bucket_id := params.get("bucket_id"):
            try:
                return resolve_cosi_bucket_auth(bucket_id)
            except grpc.RpcError as exc:
                raise _abort_from_rpc(exc) from exc

        return {}

    def DriverCreateBucket(self, vms_session, name, parameters):
        params = parse_create_bucket_params(name, parameters)
        view = provision_bucket_view(vms_session, name, params)
        apply_bucket_post_provision(vms_session, name, view, params)
        bucket_id = build_bucket_endpoint_id(vms_session, name, view, params)
        return types.DriverCreateBucketResp(
            bucket_id=bucket_id,
            bucket_info=types.Protocol(
                s3=types.S3(
                    region="N/A",
                    signature_version=types.S3SignatureVersion.UnknownSignature,
                )
            ),
        )

    def DriverDeleteBucket(self, vms_session, bucket_id, delete_context):
        parsed = BucketId.parse(bucket_id)
        vms_session.globalsnapstreams.ensure_snapshot_stream_deleted(
            name=cosi_clone_stream_name(parsed.name)
        )
        vms_session.snapshots.delete(
            name=cosi_clone_snap_name(parsed.name)
        )
        if view := vms_session.views.one(bucket=parsed.name):
            vms_session.s3lifecyclerules.delete_many(view__id=view.id)
            vms_session.folders.delete(view.path, view.tenant_id)
            vms_session.views.delete_by_id(view.id)
            # Missing bucket_owner → treat as managed (pre-VCSI-328 / incomplete mocks).
            if getattr(view, "bucket_owner", parsed.name) == parsed.name:
                vms_session.users.delete(name=parsed.name)
        vms_session.quotas.delete(name=parsed.name)
        return types.DriverDeleteBucketResp()

    def DriverGrantBucketAccess(self, vms_session, bucket_id, name, parameters=None):
        parsed = BucketId.parse(bucket_id)
        return grant_bucket_access(
            vms_session,
            bucket_name=parsed.name,
            tenant_id=parsed.tenant_id,
            endpoint=parsed.endpoint,
            parameters=dict(parameters or {}),
        )

    def DriverRevokeBucketAccess(
        self, vms_session, bucket_id, account_id, revoke_access_context=None
    ):
        # revoke_access_context: COSI request field; unused by this driver
        parsed = BucketId.parse(bucket_id)
        return revoke_bucket_access(
            vms_session,
            bucket_name=parsed.name,
            account_id=account_id,
        )


def serve(server: grpc.Server, conf: Config):
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf
    cosi_identity = CosiIdentity()
    cosi_grpc.add_IdentityServicer_to_server(cosi_identity, server)

    cosi_provisioner = CosiProvisioner()
    cosi_grpc.add_ProvisionerServicer_to_server(cosi_provisioner, server)
