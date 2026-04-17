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
from random import randint
import grpc
from vast_csi.proto import cosi_pb2_grpc as cosi_grpc
from vast_csi import csi_types as types
from vast_csi.exceptions import MissingParameter
from vast_csi.plugins.base import Instrumented
from vast_csi.configuration import Config


CONF = None


class CosiIdentity(cosi_grpc.IdentityServicer, Instrumented):

    def DriverGetInfo(self, request, context):
        return types.DriverGetInfoResp(name=CONF.plugin_name)


class CosiProvisioner(cosi_grpc.ProvisionerServicer, Instrumented):

    def DriverCreateBucket(self, vms_session, name, parameters):
        if (root_export := parameters.pop("root_export", None)) is None:
            raise MissingParameter(param="root_export")
        if not (vip_pool_name := parameters.pop("vip_pool_name", None)):
            raise MissingParameter(param="vip_pool_name")
        scheme = parameters.pop("scheme", "http")

        if CONF.truncate_volume_name:
            name = name[:CONF.truncate_volume_name]  # crop to Vast's max-length

        uid = randint(50000, 60000)
        vms_session.users.ensure(name=name, uid=uid)
        view = vms_session.views.ensure_s3view(bucket_name=name, root_export=root_export, **parameters)
        port = 443 if scheme == "https" else 80
        vip = vms_session.vippools.get_vip(vip_pool_name=vip_pool_name, tenant_id=view.tenant_id)
        # bucket_id contains bucket name and endpoint
        # should be smth like test-bucket-caf9e0d0-0b9a-4b5e-8b0a-9b0brb0b4c0c@1@https://172.0.0.1:443
        return types.DriverCreateBucketResp(
            bucket_id=f"{name}@{view.tenant_id}@{scheme}://{vip}:{port}",
            bucket_info=types.Protocol(
                s3=types.S3(
                    region="N/A",
                    signature_version=types.S3SignatureVersion.UnknownSignature
                )
            )
        )

    def DriverDeleteBucket(self, vms_session, bucket_id, delete_context):
        bucket_id, _, _ = bucket_id.split('@')
        if view := vms_session.views.one(bucket=bucket_id):
            vms_session.folders.delete(view.path, view.tenant_id)
            vms_session.views.delete_by_id(view.id)
        vms_session.users.delete(name=bucket_id)
        return types.DriverDeleteBucketResp()

    def DriverGrantBucketAccess(self, vms_session, bucket_id, name):
        bucket_id, _, endpoint = bucket_id.split('@')
        user = vms_session.users.one(name=bucket_id)
        creds = vms_session.users.generate_access_key(user.id)
        credentials = dict(
            s3=types.CredentialDetails(
                secrets={"accessKeyID": creds.access_key, "accessSecretKey": creds.secret_key, "endpoint": endpoint}
            )
        )
        return types.DriverGrantBucketAccessResp(
            account_id=creds.access_key,
            credentials=credentials
        )

    def DriverRevokeBucketAccess(self, vms_session, bucket_id, account_id):
        bucket_id, _, _ = bucket_id.split('@')
        if user := vms_session.users.one(name=bucket_id):
            vms_session.users.delete_access_key(user.id, account_id)
        return types.DriverRevokeBucketAccessResp()


def serve(server: grpc.Server, conf: Config):
    global CONF
    import vast_csi.plugins.base

    vast_csi.plugins.base.CONF = CONF = conf
    cosi_identity = CosiIdentity()
    cosi_grpc.add_IdentityServicer_to_server(cosi_identity, server)

    cosi_provisioner = CosiProvisioner()
    cosi_grpc.add_ProvisionerServicer_to_server(cosi_provisioner, server)
