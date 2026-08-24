import json
from dataclasses import dataclass, field
from datetime import timedelta
from hashlib import sha256
from random import randint
from typing import final, Optional

from easypy.humanize import yesno_to_bool

from vast_csi.csi_types import ALREADY_EXISTS, INVALID_ARGUMENT, NOT_FOUND
from vast_csi.exceptions import Abort, MissingParameter
from vast_csi.quantity import parse_quantity
from vast_csi.session.vms_session import VmsSession

_VMS_NAME_MAX_LEN = 64

# COSI sidecar builds bucket name as BucketClass.name + BucketClaim.uid.
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
_ANNOTATION_PREFIX = "cosi.vastdata.com/"
_PARAM_SOURCE_BUCKET = f"{_ANNOTATION_PREFIX}sourceBucket"
_PARAM_BLOCKING_CLONES = f"{_ANNOTATION_PREFIX}blockingClones"
_PARAM_BUCKET_OWNER_ENFORCED = f"{_ANNOTATION_PREFIX}bucketOwnerEnforced"
_PARAM_CLAIM_MAX_SIZE = f"{_ANNOTATION_PREFIX}maxSize"

__all__ = [
    "BucketProvisionBase",
    "CreateBucketParams",
    "EmptyBucketBuilder",
    "CloneBucketBuilder",
    "apply_bucket_post_provision",
    "build_bucket_endpoint_id",
    "cosi_clone_resource_name",
    "cosi_clone_snap_name",
    "cosi_clone_stream_name",
    "parse_create_bucket_params",
    "parse_lifecycle_rules",
    "provision_bucket_view",
]


def cosi_clone_resource_name(prefix: str, bucket_name: str) -> str:
    candidate = f"{prefix}{bucket_name}"
    if len(candidate) <= _VMS_NAME_MAX_LEN:
        return candidate
    digest = sha256(bucket_name.encode()).hexdigest()[:10]
    tail_room = _VMS_NAME_MAX_LEN - len(prefix) - len(digest) - 1
    return f"{prefix}{bucket_name[:tail_room]}-{digest}"


def cosi_clone_snap_name(bucket_name: str) -> str:
    return cosi_clone_resource_name("cosi-snp-", bucket_name)


def cosi_clone_stream_name(bucket_name: str) -> str:
    return cosi_clone_resource_name("cosi-strm-", bucket_name)


def parse_lifecycle_rules(raw, bucket_name):
    """Parse BucketClass lifecycle_rules JSON into (name, params) pairs for VMS."""
    if raw is None or raw == "":
        return []
    try:
        rules = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Abort(INVALID_ARGUMENT, f"lifecycle_rules is not valid JSON: {exc}")
    if not isinstance(rules, list):
        raise Abort(INVALID_ARGUMENT, "lifecycle_rules must be a JSON array")

    allowed_keys = set(_LIFECYCLE_RULE_KEYS) | {"name"}
    parsed = []
    seen_names = set()
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise Abort(INVALID_ARGUMENT, f"lifecycle_rules[{i}] must be an object")
        unknown = set(rule) - allowed_keys
        if unknown:
            raise Abort(
                INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] unknown key(s): {', '.join(sorted(unknown))}",
            )
        if "expiration_days" in rule and "expiration_date" in rule:
            raise Abort(
                INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] cannot set both expiration_days and expiration_date",
            )
        if not any(key in rule for key in _LIFECYCLE_ACTION_KEYS):
            raise Abort(
                INVALID_ARGUMENT,
                f"lifecycle_rules[{i}] needs at least one action field "
                f"({', '.join(_LIFECYCLE_ACTION_KEYS)})",
            )
        name = rule.get("name") or f"cosi-{bucket_name}-{i}"
        if name in seen_names:
            raise Abort(INVALID_ARGUMENT, f"lifecycle_rules[{i}] duplicate name {name!r}")
        seen_names.add(name)
        params = {key: rule[key] for key in _LIFECYCLE_RULE_KEYS if key in rule}
        params.setdefault("enabled", True)
        parsed.append((name, params))
    return parsed


@dataclass
class CreateBucketParams:
    root_export: str
    vip_pool_name: str
    scheme: str = "http"
    lifecycle_rules: list = field(default_factory=list)
    requested_capacity: Optional[int] = None
    source_bucket: str | None = None
    blocking_clones: bool = False
    bucket_owner_enforced: bool = True
    remaining_parameters: dict = field(default_factory=dict)


def parse_create_bucket_params(name: str, parameters: dict) -> CreateBucketParams:
    # protobuf ScalarMapContainer.pop(missing, default) ignores default and
    # returns "" for string maps — copy to a real dict first.
    parameters = dict(parameters)

    if (root_export := parameters.pop("root_export", None)) is None:
        raise MissingParameter(param="root_export")
    if not (vip_pool_name := parameters.pop("vip_pool_name", None)):
        raise MissingParameter(param="vip_pool_name")
    scheme = parameters.pop("scheme", "http")
    lifecycle_rules_raw = parameters.pop("lifecycle_rules", None)

    # Claim annotation (via bucket-params webhook) overrides BucketClass max_size.
    claim_max_size = parameters.pop(_PARAM_CLAIM_MAX_SIZE, None) or None
    class_max_size = parameters.pop("max_size", None) or None
    max_size = claim_max_size or class_max_size

    requested_capacity = None
    if max_size:
        try:
            requested_capacity = int(parse_quantity(max_size))
        except ValueError as exc:
            raise Abort(INVALID_ARGUMENT, f"Invalid max_size {max_size!r}: {exc}")
        if requested_capacity <= 0:
            raise Abort(INVALID_ARGUMENT, f"max_size must be positive, got {max_size!r}")

    if len(name) > VAST_MAX_BUCKET_NAME_LENGTH:
        class_max = VAST_MAX_BUCKET_NAME_LENGTH - K8S_UID_LENGTH
        raise Abort(
            INVALID_ARGUMENT,
            f"Bucket name {name!r} has {len(name)} characters; "
            f"maximum allowed is {VAST_MAX_BUCKET_NAME_LENGTH}. "
            f"COSI builds the name as BucketClass name + BucketClaim UID ({K8S_UID_LENGTH} chars). "
            f"Use a BucketClass name of at most {class_max} characters.",
        )

    lifecycle_rules = parse_lifecycle_rules(lifecycle_rules_raw, name)

    source_bucket = parameters.pop(_PARAM_SOURCE_BUCKET, None)
    blocking_raw = parameters.pop(_PARAM_BLOCKING_CLONES, None)
    owner_raw = parameters.pop(_PARAM_BUCKET_OWNER_ENFORCED, None)

    blocking_clones = False
    bucket_owner_enforced = True
    if source_bucket:
        if blocking_raw is not None:
            blocking_clones = yesno_to_bool(str(blocking_raw))
        if owner_raw is not None:
            bucket_owner_enforced = yesno_to_bool(str(owner_raw))
    elif blocking_raw is not None or owner_raw is not None:
        raise Abort(
            INVALID_ARGUMENT,
            "clone parameters (cosi.vastdata.com/blockingClones, "
            "cosi.vastdata.com/bucketOwnerEnforced) "
            f"require {_PARAM_SOURCE_BUCKET}",
        )

    # Claim annotations must not leak into ensure_s3view kwargs.
    remaining = {
        key: value
        for key, value in parameters.items()
        if not key.startswith(_ANNOTATION_PREFIX)
    }

    return CreateBucketParams(
        root_export=root_export,
        vip_pool_name=vip_pool_name,
        scheme=scheme,
        lifecycle_rules=lifecycle_rules,
        requested_capacity=requested_capacity,
        source_bucket=source_bucket,
        blocking_clones=blocking_clones,
        bucket_owner_enforced=bucket_owner_enforced,
        remaining_parameters=remaining,
    )


def provision_bucket_view(vms_session: VmsSession, name: str, params: CreateBucketParams):
    if params.source_bucket:
        return CloneBucketBuilder(
            vms_session=vms_session,
            name=name,
            root_export=params.root_export,
            source_bucket=params.source_bucket,
            blocking_clones=params.blocking_clones,
            bucket_owner_enforced=params.bucket_owner_enforced,
            remaining_parameters=params.remaining_parameters,
        ).build()
    return EmptyBucketBuilder(
        vms_session=vms_session,
        name=name,
        root_export=params.root_export,
        remaining_parameters=params.remaining_parameters,
    ).build()


def apply_bucket_post_provision(
    vms_session: VmsSession, name: str, view, params: CreateBucketParams
):
    for rule_name, rule_params in params.lifecycle_rules:
        vms_session.s3lifecyclerules.ensure(name=rule_name, view_id=view.id, **rule_params)

    if not params.requested_capacity:
        return
    if existing := vms_session.quotas.one(path=view.path, tenant_id=view.tenant_id):
        if existing.hard_limit not in (None, params.requested_capacity):
            raise Abort(
                ALREADY_EXISTS,
                f"Bucket already exists with different max_size ({existing.hard_limit})",
            )
    else:
        vms_session.quotas.ensure(
            volume_id=name,
            view_path=view.path,
            tenant_id=view.tenant_id,
            requested_capacity=params.requested_capacity,
        )


def build_bucket_endpoint_id(
    vms_session: VmsSession, name: str, view, params: CreateBucketParams
) -> str:
    port = 443 if params.scheme == "https" else 80
    vip = vms_session.vippools.get_vip(
        vip_pool_name=params.vip_pool_name, tenant_id=view.tenant_id
    )
    return f"{name}@{view.tenant_id}@{params.scheme}://{vip}:{port}"


@dataclass(kw_only=True)
class BucketProvisionBase:
    """Common builder with shared methods/attributes for COSI buckets."""

    vms_session: VmsSession
    name: str
    root_export: str
    remaining_parameters: dict = field(default_factory=dict)

    def _ensure_bucket_user(self):
        self.vms_session.users.ensure(name=self.name, uid=randint(50000, 60000))


@final
@dataclass(kw_only=True)
class EmptyBucketBuilder(BucketProvisionBase):
    """Builder for a regular empty COSI bucket (S3 view + bucket owner user)."""

    def build(self):
        self._ensure_bucket_user()
        return self.vms_session.views.ensure_s3view(
            bucket_name=self.name,
            root_export=self.root_export,
            **self.remaining_parameters,
        )


@final
@dataclass(kw_only=True)
class CloneBucketBuilder(BucketProvisionBase):
    """Writable COSI bucket clone via snapshot + GSS + S3 view.

    Snap/stream VMS names are derived from the claim bucket name only
    (cosi-snp-{name}, cosi-strm-{name}). globalsnapstreams.ensure is
    idempotent by name and does not re-validate destination_path on
    retry — same contract as NFS clone builders; one name per bucket claim.

    On partial failure, CreateBucket retry reuses existing snap/GSS by name;
    do not roll them back on transient errors. Full cleanup is
    DriverDeleteBucket (GSS + snap + view + user) or snap expiry (5 min).
    """

    source_bucket: str
    blocking_clones: bool = False
    bucket_owner_enforced: bool = True

    @property
    def dest_path(self) -> str:
        root_export = self.root_export.strip("/")
        return f"/{root_export}/{self.name}" if root_export else f"/{self.name}"

    def build(self):
        source_view = self.vms_session.views.one(bucket=self.source_bucket)
        if not source_view:
            raise Abort(NOT_FOUND, f"Unknown source bucket: {self.source_bucket}")

        view_policy_name = self.remaining_parameters.get("view_policy", "s3_default_policy")
        dest_view_policy = self.vms_session.viewpolicies.one(
            name=view_policy_name, fail_if_missing=True
        )
        if dest_view_policy.tenant_id != source_view.tenant_id:
            raise Abort(
                INVALID_ARGUMENT,
                f"view_policy tenant_id {dest_view_policy.tenant_id} does not match "
                f"source bucket tenant_id {source_view.tenant_id}",
            )

        tenant_id = source_view.tenant_id
        source_path = source_view.path

        self._ensure_bucket_user()
        try:
            snapshot = self.vms_session.snapshots.ensure(
                name=cosi_clone_snap_name(self.name),
                path=source_path,
                tenant_id=tenant_id,
                expiration_delta=timedelta(minutes=5),
            )
            self.vms_session.globalsnapstreams.ensure(
                name=cosi_clone_stream_name(self.name),
                snapshot_id=snapshot.id,
                destination_path=self.dest_path,
                tenant_id=tenant_id,
                wait=self.blocking_clones,
            )

            s3_kwargs = dict(self.remaining_parameters)
            s3_kwargs.pop("create_dir", None)
            if self.bucket_owner_enforced:
                s3_kwargs["s3_object_ownership_rule"] = "BucketOwnerEnforced"

            view = self.vms_session.views.ensure_s3view(
                bucket_name=self.name,
                root_export=self.root_export,
                **s3_kwargs,
                create_dir=False,
            )
            if view.path.rstrip("/") != self.dest_path.rstrip("/"):
                raise Abort(
                    ALREADY_EXISTS,
                    f"Bucket {self.name!r} already exists at {view.path!r}, expected {self.dest_path!r}",
                )
            return view
        except Abort:
            raise  # keep bucket owner; existing view may already use it
        except Exception:
            self.vms_session.users.delete(name=self.name)
            raise
