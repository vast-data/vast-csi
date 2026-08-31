# Copyright 2026 VAST Data Inc.
# All Rights Reserved.
from dataclasses import dataclass

# Customer BucketClass contexts only. ``aggregated`` is used internally for
# origins checks (see resolve_existing_bucket_owner), not as a public value.
_VALID_CONTEXTS = frozenset({"ad", "ldap", "local", "nis"})


class OwnerConfigError(ValueError):
    pass


class OwnerNotFoundError(OwnerConfigError):
    pass


@dataclass(frozen=True)
class OwnerSpec:
    """Managed owner when username is None; else existing VMS/AD user."""

    username: str | None = None
    context: str | None = None  # required when username is set

    @property
    def is_managed(self) -> bool:
        return self.username is None


def resolve_owner(parameters: dict, *, bucket_name: str) -> OwnerSpec:
    owner = (parameters.pop("bucket_owner", None) or "").strip()
    context = (parameters.pop("bucket_owner_context", None) or "").strip().lower()
    if not owner:
        if context:
            raise OwnerConfigError(
                "bucket_owner_context requires bucket_owner"
            )
        return OwnerSpec()
    if not context:
        raise OwnerConfigError(
            "bucket_owner_context is required when bucket_owner is set"
        )
    if context not in _VALID_CONTEXTS:
        raise OwnerConfigError(f"invalid bucket_owner_context: {context!r}")
    # Delete uses view.bucket_owner == bucket name as the managed-user signal.
    # Existing owners must not collide with that bit.
    if owner == bucket_name:
        raise OwnerConfigError(
            f"bucket_owner {owner!r} must differ from the bucket name"
        )
    return OwnerSpec(username=owner, context=context)


def resolve_existing_bucket_owner(vms_session, owner: OwnerSpec, tenant_id) -> str:
    queried = vms_session.users.query_user(
        username=owner.username,
        tenant_id=tenant_id,
        context=owner.context,
    )
    if not (owner_name := getattr(queried, "name", None)):
        raise OwnerNotFoundError(
            f"bucket owner {owner.username!r} not found in "
            f"bucket_owner_context={owner.context!r}",
        )
    # Lowercase aggregated (see User.query_user): uppercase AGGREGATED
    # returns empty origins on VMS 5.5.x.
    aggregated = vms_session.users.query_user(
        username=owner.username,
        tenant_id=tenant_id,
        context="aggregated",
    )
    if not getattr(aggregated, "name", None):
        raise OwnerNotFoundError(
            f"bucket owner {owner.username!r} not found",
        )
    assert_owner_origin(
        aggregated,
        owner.context,
        explicit_context_resolved=True,
    )
    # VMS S3 views store login_name for LDAP/AD (e.g. user1@domain), not
    # the short users/query name. Prefer login_name so ensure_s3view create
    # and idempotent owner compare stay aligned with the view.
    login_name = (getattr(queried, "login_name", None) or "").strip()
    return login_name or owner_name


def assert_owner_origin(
    aggregated_query,
    context: str,
    *,
    explicit_context_resolved: bool = False,
) -> None:
    """Fail if VMS origins do not match explicit bucket_owner_context.

    Call with users/query using lowercase ``context=aggregated`` (or omit
    context). Explicit-context queries (``local`` / ``ad`` / ``ldap`` / …)
    never populate ``origins`` on VMS 5.5+ — only the aggregated/default
    merge response carries ``origins.name`` (VAST user-query docs).

    Wire quirk (lab 5.5.0.1): ``context=AGGREGATED`` (uppercase) returns
    ``origins: {}`` for every local user; ``context=aggregated`` or omitting
    context returns ``origins.name=LOCAL``. ``User.query_user`` therefore
    keeps ``aggregated`` lowercase so this check can actually run.

    Soft-pass: if ``origins.name`` is still empty after that correct query,
    and the caller already got a ``name`` from
    ``users/query(context=bucket_owner_context)``
    (``explicit_context_resolved=True``), accept the owner. Hedge for VMS
    cases still seen empty on LDAP-primary tenants / flaky merge (prior
    VCSI-328 e2e). Non-empty mismatch (e.g. ``LDAP`` vs ``local``) still
    fails — soft-pass is empty-only, not a wrong-origin bypass.
    """
    expected = context.upper()
    actual = (getattr(aggregated_query, "origins", {}) or {}).get("name", "")
    if str(actual).upper() == expected:
        return
    if not actual and explicit_context_resolved:
        return
    raise OwnerConfigError(
        f"bucket owner origins.name={actual!r} does not match "
        f"bucket_owner_context={context!r}"
    )
