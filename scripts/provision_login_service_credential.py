"""One-time provisioning of the Login Service's own ZITADEL machine-user
credential (docs/ADR/0017-product-owned-zitadel-login-service.md, Security
requirements).

Uses the existing bootstrap machine user's PAT (the same
IAM_OWNER-scoped, LOCAL/BOOTSTRAP-only credential
`scripts/configure_zitadel_login_v2.py` already documents and reuses for
exactly this kind of one-time administrative action -- never the Login
Service's own runtime credential) to, in this order:

1. Find-or-create a dedicated ZITADEL machine user named
   `LOGIN_SERVICE_ZITADEL_USERNAME` (default `login-service`) via
   `zitadel.user.v2.UserService.CreateUser` (`POST /v2/users`,
   `machine{...}`) -- a NEW identity, never the bootstrap machine user
   itself.
2. Grant that machine user the `IAM_LOGIN_CLIENT` role via the legacy
   Admin API's `AddIAMMember` (`POST /admin/v1/members`, permission
   `iam.member.write`) -- verified (`cmd/defaults.yaml` at the pinned
   ZITADEL version) as the ONLY built-in ZITADEL role that carries
   `session.link` (required for `CreateCallback`); no narrower built-in
   role exists. `IAM_LOGIN_CLIENT` is broader than the theoretical
   minimum (it also carries `user.write`/`org.member.write`/
   `iam.member.write`) but does NOT carry `project.app.write` -- the
   Login Service's runtime credential still cannot reconfigure
   applications, satisfying the required separation from
   `scripts/configure_zitadel_login_v2.py`'s own credential. **This step
   runs before any key exists (security audit F-02): success or an
   already-a-member 409 continues; any other failure aborts the whole
   run immediately -- no key is created and no credential file is ever
   written for a machine user whose required authorization could not be
   confirmed.**
3. Reconcile keys, then generate a fresh RSA keypair locally (the private
   key never leaves this process/host) and register only the PUBLIC key
   via `UserService.AddKey` (`POST /v2/users/{user_id}/keys`, permission
   `user.write`) -- exactly the "deploy-time generated private key ->
   private-key JWT" mechanism ADR-0017 requires. ZITADEL never sees the
   private key. **Security audit F-01**: if the local credential files
   are absent, this process has no recoverable private key for any
   already-registered key on this user (a lost private key can never be
   retrieved from ZITADEL), so every key already on this user is listed
   first (`UserService.ListKeys`, filtered strictly to this one
   `user_id` -- never a tenant-wide query), a replacement is created and
   verified, and only THEN are the previously-listed (now obsolete) keys
   removed (`UserService.RemoveKey`) -- never before the replacement is
   confirmed to exist, and never a key that does not belong to this
   dedicated user.

Idempotent: if the local output files (private key + recorded
user_id/key_id) already exist, this script does nothing and exits 0 --
re-running it is safe. It never overwrites an existing local private key
(re-provisioning on purpose means deleting the local output directory
first, a deliberate, visible action, never automatic here). When those
files are absent, re-running is still safe: the reconciliation in step 3
above prevents unbounded key accumulation on the ZITADEL side.

Output (all gitignored, never committed -- see .gitignore's
`deploy/login-service/` entry):
    deploy/login-service/private_key.pem
    deploy/login-service/service_user_id.txt
    deploy/login-service/key_id.txt

These three values are exactly `LOGIN_SERVICE_PRIVATE_KEY_PATH`,
`LOGIN_SERVICE_ZITADEL_USER_ID`, `LOGIN_SERVICE_ZITADEL_KEY_ID` in
`.env`/docker-compose.yml.
"""

from __future__ import annotations

import base64
import os
import sys
import time

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEFAULT_PAT_PATH = "/bootstrap/bootstrap.pat"
DEFAULT_PROJECT_NAME = "product"
DEFAULT_USERNAME = "login-service"
_RETRIES = 15
_RETRY_DELAY_SECONDS = 2.0
_KEY_LIFETIME_SECONDS = 10 * 365 * 24 * 60 * 60  # 10y -- rotated by re-provisioning, not expiry
_IAM_LOGIN_CLIENT_ROLE = "IAM_LOGIN_CLIENT"


class ProvisioningError(RuntimeError):
    """Never carries the PAT or the generated private key."""


class ProvisioningApiError(ProvisioningError):
    """A definitive (non-transient) rejection from ZITADEL -- a 4xx status,
    never retried. Carries the status code so callers can special-case a
    specific, expected outcome (e.g. 409 Already Exists) without treating
    every failure the same."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"ZITADEL API call failed: {status_code} {reason}")
        self.status_code = status_code


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def read_pat(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:
        raise ProvisioningError(
            f"Could not read the bootstrap PAT from {path!r}: {type(exc).__name__}."
        ) from None


def _call(client: httpx.Client, method: str, path: str, json: dict | None = None) -> dict:
    """Retries transport errors and 5xx responses (ZITADEL still starting
    up, a dropped connection) -- never a 4xx, which is a definitive
    rejection (e.g. 409 Already Exists) that retrying cannot fix and would
    only mask behind 15 identical attempts."""
    last_error: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            response = client.request(method, path, json=json)
        except httpx.TransportError as exc:
            last_error = exc
            print(
                f"[provision-login-service] {method} {path} failed "
                f"(attempt {attempt}/{_RETRIES}): {type(exc).__name__}",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
            continue

        if response.status_code >= 500:
            last_error = ProvisioningApiError(response.status_code, "server error")
            print(
                f"[provision-login-service] {method} {path} failed "
                f"(attempt {attempt}/{_RETRIES}): {response.status_code}",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
            continue

        if response.status_code >= 400:
            raise ProvisioningApiError(response.status_code, "request rejected")
        return response.json() if response.content else {}

    raise ProvisioningError(f"{method} {path} failed after {_RETRIES} attempts") from last_error


def get_org_id(client: httpx.Client) -> str:
    body = _call(client, "GET", "/management/v1/orgs/me")
    return body["org"]["id"]


def find_existing_machine_user(client: httpx.Client, *, org_id: str, username: str) -> str | None:
    """`ListUsers` -- verified proto: `POST /v2/users` (not `/v2/users/new`,
    which is `CreateUser`; ZITADEL's own proto comment notes the `/new`
    suffix exists specifically to avoid colliding with this path)."""
    listing = _call(
        client,
        "POST",
        "/v2/users",
        json={
            "queries": [
                {"organizationIdQuery": {"organizationId": org_id}},
                {"userNameQuery": {"userName": username, "method": "TEXT_QUERY_METHOD_EQUALS"}},
            ]
        },
    )
    users = listing.get("result", [])
    if not users:
        return None
    return users[0]["userId"]


def create_machine_user(client: httpx.Client, *, org_id: str, username: str) -> str:
    """Verified proto: `POST /v2/users/new`, response field `id`."""
    body = _call(
        client,
        "POST",
        "/v2/users/new",
        json={
            "organizationId": org_id,
            "username": username,
            "machine": {
                "name": username,
                "description": (
                    "Marketstack Login Service (docs/ADR/0017) -- calls the ZITADEL Session "
                    "API to authenticate end users on the product's own branded login page. "
                    "Never used for application configuration."
                ),
                "accessTokenType": "ACCESS_TOKEN_TYPE_BEARER",
            },
        },
    )
    return body["id"]


def generate_keypair() -> tuple[bytes, bytes]:
    """Returns (private_key_pem, public_key_pem). The private key never
    leaves this process except to be written to the local, gitignored
    output file."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def add_key(client: httpx.Client, *, user_id: str, public_key_pem: bytes) -> str:
    expiration = time.strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z", time.gmtime(time.time() + _KEY_LIFETIME_SECONDS)
    )
    body = _call(
        client,
        "POST",
        f"/v2/users/{user_id}/keys",
        json={
            "expirationDate": expiration,
            "publicKey": base64.b64encode(public_key_pem).decode("ascii"),
        },
    )
    return body["keyId"]


def list_key_ids(client: httpx.Client, *, user_id: str) -> list[str]:
    """`UserService.ListKeys` -- verified proto: `POST /v2/users/keys/search`,
    permission `user.read`. Filtered strictly to this one `user_id`
    (`IDFilter{id: user_id}`, `zitadel/filter/v2/filter.proto`) -- never a
    tenant-wide query (security audit F-01: this must never see, and
    therefore can never touch, another machine user's keys).

    Note the response's own `Key.id` field (`zitadel/user/v2/key.proto`)
    -- NOT `keyId`, which is `AddKeyResponse`'s own, differently-named
    field for the same concept."""
    body = _call(
        client,
        "POST",
        "/v2/users/keys/search",
        json={"filters": [{"userIdFilter": {"id": user_id}}]},
    )
    return [key["id"] for key in body.get("result", []) if "id" in key]


def remove_key(client: httpx.Client, *, user_id: str, key_id: str) -> None:
    """`UserService.RemoveKey` -- verified proto:
    `DELETE /v2/users/{user_id}/keys/{key_id}`, permission `user.write`.
    ZITADEL's own proto comment: succeeds whether the key existed or not
    -- safe to call on a key that is already gone."""
    _call(client, "DELETE", f"/v2/users/{user_id}/keys/{key_id}")


# Verified live: {"code":6,"message":"Errors.Instance.Member.AlreadyExists"}
_ALREADY_MEMBER_STATUS = 409


def grant_iam_login_client_role(client: httpx.Client, *, user_id: str) -> None:
    """Fail-closed (security audit F-02): success or an already-a-member
    409 return normally; any other failure raises `ProvisioningError`,
    aborting `provision()` before any key is created or any credential
    file is written. A Login Service credential must never be published
    for a machine user whose required IAM authorization could not be
    confirmed -- a bare warning here previously let that happen."""
    try:
        _call(
            client,
            "POST",
            "/admin/v1/members",
            json={"userId": user_id, "roles": [_IAM_LOGIN_CLIENT_ROLE]},
        )
        print(f"[provision-login-service] granted {_IAM_LOGIN_CLIENT_ROLE} to {user_id!r}")
    except ProvisioningApiError as exc:
        if exc.status_code == _ALREADY_MEMBER_STATUS:
            print(
                f"[provision-login-service] {user_id!r} already has {_IAM_LOGIN_CLIENT_ROLE} "
                "-- no action needed."
            )
            return
        raise ProvisioningError(
            f"Could not grant {_IAM_LOGIN_CLIENT_ROLE} to {user_id!r} ({exc}). Refusing to "
            "create a key or publish a credential without confirmed IAM authorization -- "
            "verify manually in the ZITADEL console (Instance -> Members) and re-run."
        ) from exc


def provision(*, output_dir: str, transport: httpx.BaseTransport | None = None) -> None:
    key_path = os.path.join(output_dir, "private_key.pem")
    user_id_path = os.path.join(output_dir, "service_user_id.txt")
    key_id_path = os.path.join(output_dir, "key_id.txt")

    if os.path.exists(key_path) and os.path.exists(user_id_path) and os.path.exists(key_id_path):
        print(
            f"[provision-login-service] already provisioned ({output_dir}) -- no action taken."
        )
        return

    zitadel_url = _env("ZITADEL_INTERNAL_URL")
    if not zitadel_url:
        raise ProvisioningError("ZITADEL_INTERNAL_URL must be set.")
    pat_path = _env("ZITADEL_BOOTSTRAP_PAT_PATH", DEFAULT_PAT_PATH)
    assert pat_path is not None
    project_name = _env("OIDC_LOCAL_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    assert project_name is not None
    username = _env("LOGIN_SERVICE_ZITADEL_USERNAME", DEFAULT_USERNAME)
    assert username is not None

    pat = read_pat(pat_path)
    with httpx.Client(
        base_url=zitadel_url,
        headers={"Authorization": f"Bearer {pat}"},
        timeout=10.0,
        transport=transport,
    ) as client:
        org_id = get_org_id(client)
        user_id = find_existing_machine_user(client, org_id=org_id, username=username)
        if user_id is None:
            user_id = create_machine_user(client, org_id=org_id, username=username)
            print(f"[provision-login-service] created machine user {username!r}: {user_id}")
        else:
            print(
                f"[provision-login-service] reusing existing machine user "
                f"{username!r}: {user_id}"
            )

        # F-02: required authorization must be confirmed before any key
        # exists or any credential is published. Raises (aborting this
        # entire run, no key created, no file written) on any failure
        # other than an already-a-member 409.
        grant_iam_login_client_role(client, user_id=user_id)

        # F-01: reaching this point means the local credential files are
        # absent (the already-provisioned fast path above returned
        # earlier otherwise), so this process holds no recoverable
        # private key for any key already registered on this user --
        # every one of them is obsolete. List them now, before creating
        # the replacement, strictly scoped to this one dedicated user.
        obsolete_key_ids = list_key_ids(client, user_id=user_id)

        private_pem, public_pem = generate_keypair()
        key_id = add_key(client, user_id=user_id, public_key_pem=public_pem)
        if not key_id:
            raise ProvisioningError("AddKey response carried no keyId.")
        print(f"[provision-login-service] registered key {key_id!r} for user {user_id!r}")

        # Only now, with the replacement confirmed created, retire the
        # obsolete keys -- never before, and never the new key itself
        # (it cannot appear in obsolete_key_ids, which was listed prior
        # to its creation). A cleanup failure does not fail the run: the
        # new credential is already valid and in use at this point.
        for obsolete_key_id in obsolete_key_ids:
            try:
                remove_key(client, user_id=user_id, key_id=obsolete_key_id)
                print(f"[provision-login-service] removed obsolete key {obsolete_key_id!r}")
            except ProvisioningApiError as exc:
                print(
                    f"[provision-login-service] WARNING: could not remove obsolete key "
                    f"{obsolete_key_id!r} ({exc}). The new key {key_id!r} is valid and in "
                    "use; remove the stale key manually if desired.",
                    file=sys.stderr,
                )

    os.makedirs(output_dir, exist_ok=True)
    with open(key_path, "wb") as f:
        f.write(private_pem)
    with open(user_id_path, "w", encoding="utf-8") as f:
        f.write(user_id)
    with open(key_id_path, "w", encoding="utf-8") as f:
        f.write(key_id)
    print(f"[provision-login-service] wrote {key_path}, {user_id_path}, {key_id_path}")
    print(
        "[provision-login-service] set LOGIN_SERVICE_ZITADEL_USER_ID="
        f"{user_id} and LOGIN_SERVICE_ZITADEL_KEY_ID={key_id} (non-secret ids; the private "
        "key itself is mounted from the file above, never copied into .env)."
    )


def main() -> None:
    output_dir = _env("LOGIN_SERVICE_CREDENTIAL_DIR", "deploy/login-service")
    assert output_dir is not None
    try:
        provision(output_dir=output_dir)
    except ProvisioningError as exc:
        print(f"[provision-login-service] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
