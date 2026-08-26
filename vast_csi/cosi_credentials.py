# Copyright 2026 VAST Data Inc.
# All Rights Reserved.
import re
from dataclasses import dataclass

import grpc
from requests.exceptions import HTTPError

from vast_csi import csi_types as types
from vast_csi.csi_types import (
    ALREADY_EXISTS,
    FAILED_PRECONDITION,
    GRPC_TO_CSI,
    INTERNAL,
    INVALID_ARGUMENT,
    RESOURCE_EXHAUSTED,
    UNKNOWN,
)
from vast_csi.exceptions import Abort, ApiError, LookupFieldError
from vast_csi.extensions_client import resolve_secret

ACCESS_KEY_FIELD = "accessKeyID"
SECRET_KEY_FIELD = "accessSecretKey"
ACCESS_KEY_RE = re.compile(r"^[A-Z0-9]{20}$")
SECRET_KEY_RE = re.compile(r"^[a-zA-Z0-9/+]{40}$")


@dataclass(frozen=True)
class UdbGrantTarget:
    user: object


@dataclass(frozen=True)
class NonLocalGrantTarget:
    username: str
    tenant_id: object


def _validate_s3_key_pair(access_key: str, secret_key: str) -> None:
    if not ACCESS_KEY_RE.match(access_key):
        raise Abort(
            INVALID_ARGUMENT,
            "access_key must be 20 uppercase alphanumeric characters",
        )
    if not SECRET_KEY_RE.match(secret_key):
        raise Abort(
            INVALID_ARGUMENT,
            "secret_key must be 40 characters from [a-zA-Z0-9/+]",
        )


def credential_response(access_key: str, secret_key: str, endpoint: str):
    credentials = dict(
        s3=types.CredentialDetails(
            secrets={
                ACCESS_KEY_FIELD: access_key,
                SECRET_KEY_FIELD: secret_key,
                "endpoint": endpoint,
            }
        )
    )
    return types.DriverGrantBucketAccessResp(
        account_id=access_key,
        credentials=credentials,
    )


def _map_vms_force_error(exc: HTTPError | ApiError) -> Abort:
    response = getattr(exc, "response", None)
    if response is None:
        return Abort(INVALID_ARGUMENT, str(exc))
    status = response.status_code
    text = response.text or ""
    first_line = text.splitlines()[0] if text else str(exc)
    if status == 400 and "access_key_in_use" in text:
        return Abort(ALREADY_EXISTS, "access key is already in use by another user")
    if status == 400 and "key_limit_reached" in text:
        return Abort(RESOURCE_EXHAUSTED, "user has reached the maximum number of access keys")
    if status in (404, 501) or (status == 400 and "not supported" in text.lower()):
        return Abort(
            FAILED_PRECONDITION,
            f"external credentials require VAST 5.4+; VMS returned {status}: {first_line}",
        )
    if status == 400:
        return Abort(INVALID_ARGUMENT, first_line)
    if status == 403:
        return Abort(FAILED_PRECONDITION, first_line)
    if status >= 500:
        return Abort(UNKNOWN, f"VMS error during force credentials: {first_line}")
    return Abort(INVALID_ARGUMENT, first_line)


def _read_external_credentials(parameters: dict) -> tuple[str, str]:
    name = parameters.get("credentialsSecretName")
    namespace = parameters.get("credentialsSecretNamespace")
    if not name or not namespace:
        raise Abort(
            INVALID_ARGUMENT,
            "credentialsSecretName and credentialsSecretNamespace must both be set",
        )
    try:
        data = resolve_secret(name, namespace)
    except grpc.RpcError as exc:
        code = GRPC_TO_CSI.get(exc.code(), INTERNAL)
        raise Abort(code, exc.details() or str(exc)) from exc

    access_key = data.get(ACCESS_KEY_FIELD)
    secret_key = data.get(SECRET_KEY_FIELD)
    if not access_key or not secret_key:
        raise Abort(
            INVALID_ARGUMENT,
            f"Secret missing credential keys; expected "
            f"{ACCESS_KEY_FIELD} and {SECRET_KEY_FIELD}",
        )
    return access_key, secret_key


def _install_external_credentials(
    vms_session,
    *,
    user,
    tenant_id: str,
    endpoint: str,
    parameters: dict,
):
    """Install BucketAccessClass input-Secret keys onto a VAST local (UDB) user.

    Deletes existing keys then installs the forced pair (VMS cannot compare secret
    keys). Not atomic: if install fails after deletes, the user may have zero keys
    until Grant is retried.
    """
    access_key, secret_key = _read_external_credentials(parameters)
    _validate_s3_key_pair(access_key, secret_key)

    # list_access_keys uses GET /users/{id}; list-by-name may omit key material.
    for ak in vms_session.users.list_access_keys(user.id):
        try:
            vms_session.users.delete_access_key(user.id, ak)
        except (HTTPError, ApiError) as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            raise _map_vms_force_error(exc) from exc
    try:
        vms_session.users.generate_access_key(
            user.id,
            access_key=access_key,
            secret_key=secret_key,
            tenant_id=tenant_id,
        )
    except (HTTPError, ApiError) as exc:
        raise _map_vms_force_error(exc) from exc
    return credential_response(access_key, secret_key, endpoint)


def _resolve_grant_target(
    vms_session, bucket_name
) -> UdbGrantTarget | NonLocalGrantTarget:
    view = vms_session.views.one(bucket=bucket_name, fail_if_missing=True)
    owner_name = view.bucket_owner or bucket_name
    if user := vms_session.users.one(name=owner_name, tenant_id=view.tenant_id):
        return UdbGrantTarget(user=user)
    if owner_name != bucket_name:
        return NonLocalGrantTarget(username=owner_name, tenant_id=view.tenant_id)
    raise LookupFieldError(field=f"user {owner_name!r}")


def _delete_granted_key(
    vms_session, target: UdbGrantTarget | NonLocalGrantTarget, account_id
):
    if isinstance(target, UdbGrantTarget):
        vms_session.users.delete_access_key(target.user.id, account_id)
        return
    vms_session.users.delete_non_local_access_key(
        username=target.username,
        tenant_id=target.tenant_id,
        access_key=account_id,
        context="aggregated",
    )


def _wants_external_credentials(parameters: dict) -> bool:
    return bool(
        parameters.get("credentialsSecretName")
        or parameters.get("credentialsSecretNamespace")
    )


def grant_bucket_access(
    vms_session,
    *,
    bucket_name: str,
    tenant_id: str,
    endpoint: str,
    parameters: dict | None = None,
):
    """Grant S3 access on the view bucket owner (managed UDB or external).

    External keys (credentialsSecretName/Namespace) install onto UDB owners only.
    External LDAP/AD owners use VMS non_local_keys generate/delete.
    """
    parameters = dict(parameters or {})
    target = _resolve_grant_target(vms_session, bucket_name)
    external = _wants_external_credentials(parameters)

    if isinstance(target, NonLocalGrantTarget):
        if external:
            raise Abort(
                FAILED_PRECONDITION,
                "external credentials not supported for external bucket owner",
            )
        creds = vms_session.users.generate_non_local_access_key(
            username=target.username,
            tenant_id=target.tenant_id,
            context="aggregated",
        )
        return credential_response(creds.access_key, creds.secret_key, endpoint)

    if external:
        return _install_external_credentials(
            vms_session,
            user=target.user,
            tenant_id=tenant_id,
            endpoint=endpoint,
            parameters=parameters,
        )
    creds = vms_session.users.generate_access_key(target.user.id)
    return credential_response(creds.access_key, creds.secret_key, endpoint)


def revoke_bucket_access(vms_session, *, bucket_name: str, account_id: str):
    target = _resolve_grant_target(vms_session, bucket_name)
    _delete_granted_key(vms_session, target, account_id)
    return types.DriverRevokeBucketAccessResp()
