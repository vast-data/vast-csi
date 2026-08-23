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
import json
from random import randint
import grpc
from vast_csi.proto import cosi_pb2_grpc as cosi_grpc
from vast_csi import csi_types as types
from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.quantity import parse_quantity
from vast_csi.plugins.base import Instrumented
from vast_csi.configuration import Config


CONF = None

# AWS S3 / VAST max bucket name length. COSI sidecar uses BucketClass.name + BucketClaim.uid.
VAST_MAX_BUCKET_NAME_LENGTH = 63
K8S_UID_LENGTH = 36

_LIFECYCLE_ACTION_KEYS = (
    "expiration_days",
    "expiration_date",
    "noncurrent_days",
    "newer_noncurrent_versions",
    "abort_mpu_days_after_initiation",
    "expired_obj_delete_marker",
)
_LIFECYCLE_RULE_KEYS = _LIFECYCLE_ACTION_KEYS + (
    "prefix",
    "min_size",
    "max_size",
    "enabled",
    "object_age_attr",
)


def parse_lifecycle_rules(raw, bucket_name):
    """Parse BucketClass lifecycle_rules JSON into (name, params) pairs for VMS.

    Only known rule fields are accepted; unknown keys raise INVALID_ARGUMENT.
    Rule names must be unique within the array.
    """
    if raw is None or raw == "":
        return []
    try:
        rules = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Abort(types.INVALID_ARGUMENT, f"lifecycle_rules is not valid JSON: {exc}")
    if not isinstance(rules, list):
        raise Abort(types.INVALID_ARGUMENT, "lifecycle_rules must be a JSON array")

    allowed_keys = set(_LIFECYCLE_RULE_KEYS) | {"name"}
    parsed = []
    seen_names = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise Abort(types.INVALID_ARGUMENT, f"lifecycle_rules[{i}] must be an object")
        unknown = set(rule) - allowed_keys
        if unknown:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] unknown key(s): {', '.join(sorted(unknown))}",
            )
        if "expiration_days" in rule and "expiration_date" in rule:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] cannot set both expiration_days and expiration_date",
            )
        if not any(key in rule for key in _LIFECYCLE_ACTION_KEYS):
            raise Abort(
                types.INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] needs at least one action field "
                f"({', '.join(_LIFECYCLE_ACTION_KEYS)})",
            )
        name = rule.get("name") or f"cosi-{bucket_name}-{i}"
        if name in seen_names:
            raise Abort(
                types.INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] duplicate name {name!r}",
            )
        seen_names.add(name)
        params = {key: rule[key] for key in _LIFECYCLE_RULE_KEYS if key in rule}
        params.setdefault("enabled", True)
        parsed.append((name, params))
    return parsed


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
        lifecycle_rules_raw = parameters.pop("lifecycle_rules", None)

        requested_capacity = None
        if max_size := parameters.pop("max_size", None):
            try:
                requested_capacity = int(parse_quantity(max_size))
            except ValueError as exc:
                raise Abort(types.INVALID_ARGUMENT, f"Invalid max_size {max_size!r}: {exc}")
            if requested_capacity <= 0:
                raise Abort(types.INVALID_ARGUMENT, f"max_size must be positive, got {max_size!r}")

        # Never truncate: Secret/status keep the full name; crop would break credentials.
        if len(name) > VAST_MAX_BUCKET_NAME_LENGTH:
            class_max = VAST_MAX_BUCKET_NAME_LENGTH - K8S_UID_LENGTH
            raise Abort(
                types.INVALID_ARGUMENT,
                f"Bucket name {name!r} has {len(name)} characters; "
                f"maximum allowed is {VAST_MAX_BUCKET_NAME_LENGTH}. "
                f"COSI builds the name as BucketClass name + BucketClaim UID ({K8S_UID_LENGTH} chars). "
                f"Use a BucketClass name of at most {class_max} characters."
            )

        # Validate before any VMS mutation so bad JSON cannot orphan user/view.
        lifecycle_rules = parse_lifecycle_rules(lifecycle_rules_raw, name)

        uid = randint(50000, 60000)
        vms_session.users.ensure(name=name, uid=uid)
        view = vms_session.views.ensure_s3view(bucket_name=name, root_export=root_export, **parameters)

        for rule_name, rule_params in lifecycle_rules:
            vms_session.s3lifecyclerules.ensure(
                name=rule_name, view_id=view.id, **rule_params
            )

        if requested_capacity:
            if existing := vms_session.quotas.one(path=view.path, tenant_id=view.tenant_id):
                if existing.hard_limit not in (None, requested_capacity):
                    raise Abort(
                        types.ALREADY_EXISTS,
                        f"Bucket already exists with different max_size ({existing.hard_limit})",
                    )
            else:
                vms_session.quotas.ensure(
                    volume_id=name,
                    view_path=view.path,
                    tenant_id=view.tenant_id,
                    requested_capacity=requested_capacity,
                )

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
            vms_session.s3lifecyclerules.delete_many(view__id=view.id)
            vms_session.folders.delete(view.path, view.tenant_id)
            vms_session.views.delete_by_id(view.id)
        vms_session.quotas.delete(name=bucket_id)
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
