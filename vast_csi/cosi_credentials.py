# Copyright 2026 VAST Data Inc.
# All Rights Reserved.
import re

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
from vast_csi.exceptions import Abort, ApiError
from vast_csi.extensions_client import resolve_secret

ACCESS_KEY_FIELD = "accessKeyID"
SECRET_KEY_FIELD = "accessSecretKey"
ACCESS_KEY_RE = re.compile(r"^[A-Z0-9]{20}$")
SECRET_KEY_RE = re.compile(r"^[a-zA-Z0-9/+]{40}$")


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
    bucket_name: str,
    tenant_id: str,
    endpoint: str,
    parameters: dict,
):
    """Install BucketAccessClass input-Secret keys onto the bucket VAST local user.

    Deletes existing keys then installs the forced pair (VMS cannot compare secret
    keys). Not atomic: if install fails after deletes, the user may have zero keys
    until Grant is retried.
    """
    access_key, secret_key = _read_external_credentials(parameters)
    _validate_s3_key_pair(access_key, secret_key)

    # list_access_keys uses GET /users/{id}; list-by-name may omit key material.
    user = vms_session.users.one(name=bucket_name, fail_if_missing=True)
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


def grant_bucket_access(
    vms_session,
    *,
    bucket_name: str,
    tenant_id: str,
    endpoint: str,
    parameters: dict | None = None,
):
    """Grant S3 access: VMS-generated keys, or external keys from BAC Secret params."""
    parameters = dict(parameters or {})
    if parameters.get("credentialsSecretName") or parameters.get("credentialsSecretNamespace"):
        return _install_external_credentials(
            vms_session,
            bucket_name=bucket_name,
            tenant_id=tenant_id,
            endpoint=endpoint,
            parameters=parameters,
        )
    user = vms_session.users.one(name=bucket_name, fail_if_missing=True)
    creds = vms_session.users.generate_access_key(user.id)
    return credential_response(creds.access_key, creds.secret_key, endpoint)
