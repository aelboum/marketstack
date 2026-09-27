"""Marketstack-owned post-bootstrap ZITADEL SMTP configuration (mirrors
scripts/configure_zitadel_login_v2.py's own shape and reasoning almost
exactly -- read that module's docstring first if this one is unclear).

`saas-os-local-identity` (the installed `saas-os` dependency's own
bootstrap tool) has no concept of instance-level SMTP configuration --
verified against the pinned saas-os commit, which never calls any
`AdminService` email-provider RPC. Without this, ZITADEL has no SMTP
provider at all, so every notification it would send (password-reset,
invitation) silently fails to send -- this is the exact gap
`login-service/app/main.py`'s own module docstring used to list under
"Deferred, documented limitations" (password/account recovery).

This script wires ZITADEL's instance-level SMTP config to a fixed target
(Mailpit in local development; any real SMTP host in another environment,
via the same environment variables -- nothing here is Mailpit-specific
except the default host in `.env.example`) using two non-deprecated
Admin API v1 RPCs (verified against `proto/zitadel/admin.proto` +
`proto/zitadel/settings.proto`, tag v4.19.0):

    AddEmailProviderSMTP     POST /admin/v1/email/smtp        permission iam.write
    UpdateEmailProviderSMTP  PUT  /admin/v1/email/smtp/{id}    permission iam.write
    ActivateEmailProvider    POST /admin/v1/email/{id}/_activate  permission iam.write
    GetEmailProvider         GET  /admin/v1/email              permission iam.read (active only)
    GetEmailProviderById     GET  /admin/v1/email/{id}          permission iam.read

Live-verified against the pinned local ZITADEL v4.19.0 instance: a newly
added provider's own `state` is `EMAIL_PROVIDER_INACTIVE` -- despite
`AddEmailProviderSMTP`'s own proto comment ("be aware that this will be
activated as soon as it is saved," copied from the older, deprecated
`AddSMTPConfig` RPC's docstring) -- so this script always calls
`ActivateEmailProvider` explicitly after adding or updating, rather than
trusting that comment.

Configuration (environment variables):

- `ZITADEL_INTERNAL_URL` (or `OIDC_ISSUER_URL` as a fallback): required.
- `ZITADEL_BOOTSTRAP_PAT_PATH` (default `/bootstrap/bootstrap.pat`).
- `SMTP_HOST` (e.g. `mailpit:1025` -- host:port, port required by
  ZITADEL's own validation): required. Unset/empty is a safe no-op,
  mirroring `ZITADEL_LOGIN_V2_BASE_URI`'s own convention -- no SMTP
  provider is configured unless a developer/operator explicitly asks
  for one.
- `SMTP_SENDER_ADDRESS` (default `noreply@product.local`),
  `SMTP_SENDER_NAME` (default `Product`).
- `SMTP_TLS` (default `false` -- Mailpit does not speak TLS).
- `SMTP_USER`/`SMTP_PASSWORD` (optional, both empty by default -- Mailpit
  needs no authentication; set both for a real provider that does).

Idempotent: if a provider already exists with this exact
host/sender_address/sender_name/tls, no write is made beyond ensuring it
is active. If one exists with different settings, it is updated in place
(never a second, duplicate provider) and (re-)activated. Never logs,
prints, or raises with the PAT, `SMTP_PASSWORD`, or any request/response
body in it.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

DEFAULT_PAT_PATH = "/bootstrap/bootstrap.pat"
DEFAULT_SENDER_ADDRESS = "noreply@product.local"
DEFAULT_SENDER_NAME = "Product"

_RETRIES = 15
_RETRY_DELAY_SECONDS = 2.0


class SmtpConfigurationError(RuntimeError):
    """Raised for any failure in this script. Never carries the PAT,
    `SMTP_PASSWORD`, or any request/response body -- every message here is
    built from non-secret values only (ids, hosts, sender addresses)."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def read_pat(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:
        raise SmtpConfigurationError(
            f"Could not read the bootstrap PAT from {path!r}: {type(exc).__name__}. "
            "Has the zitadel-bootstrap (saas-os-local-identity) step completed?"
        ) from None


def _call(client: httpx.Client, method: str, path: str, json: dict | None = None) -> dict:
    """Retried request. Only the exception *type* is ever reported (never
    `str(exc)`), same reasoning as configure_zitadel_login_v2.py's own
    `_call()`."""
    last_error: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            response = client.request(method, path, json=json)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json() if response.content else {}
        except httpx.HTTPStatusError as exc:
            last_error = exc
            print(
                f"[configure-smtp] {method} {path} failed "
                f"(attempt {attempt}/{_RETRIES}): HTTP {exc.response.status_code}",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
        except httpx.HTTPError as exc:
            last_error = exc
            print(
                f"[configure-smtp] {method} {path} failed "
                f"(attempt {attempt}/{_RETRIES}): {type(exc).__name__}",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
    raise SmtpConfigurationError(
        f"{method} {path} failed after {_RETRIES} attempts ({type(last_error).__name__})"
    ) from None


def get_active_provider(client: httpx.Client) -> dict | None:
    """Returns the active provider's `config` object, or `None` if there is
    none yet (ZITADEL answers that case with a 404, mapped to `{}` by
    `_call()` above -- not an error condition here)."""
    body = _call(client, "GET", "/admin/v1/email")
    return body.get("config")


def desired_smtp_fields(
    *,
    host: str,
    sender_address: str,
    sender_name: str,
    tls: bool,
) -> dict:
    return {"host": host, "senderAddress": sender_address, "senderName": sender_name, "tls": tls}


def matches_desired(existing: dict, desired: dict) -> bool:
    smtp = existing.get("smtp") or {}
    return (
        smtp.get("host") == desired["host"]
        and smtp.get("senderAddress") == desired["senderAddress"]
        and smtp.get("senderName") == desired["senderName"]
        and bool(smtp.get("tls", False)) == desired["tls"]
    )


def _auth_field(user: str, password: str) -> dict:
    if user or password:
        return {"plain": {"username": user, "password": password}}
    return {"none": {}}


def add_provider(
    client: httpx.Client, *, desired: dict, reply_to_address: str, user: str, password: str
) -> str:
    body = {**desired, "replyToAddress": reply_to_address, **_auth_field(user, password)}
    result = _call(client, "POST", "/admin/v1/email/smtp", json=body)
    return result["id"]


def update_provider(
    client: httpx.Client,
    provider_id: str,
    *,
    desired: dict,
    reply_to_address: str,
    user: str,
    password: str,
) -> None:
    body = {**desired, "replyToAddress": reply_to_address, **_auth_field(user, password)}
    _call(client, "PUT", f"/admin/v1/email/smtp/{provider_id}", json=body)


def activate_provider(client: httpx.Client, provider_id: str) -> None:
    _call(client, "POST", f"/admin/v1/email/{provider_id}/_activate", json={})


def verify_active(client: httpx.Client, provider_id: str, desired: dict) -> None:
    body = _call(client, "GET", f"/admin/v1/email/{provider_id}")
    config = body.get("config") or {}
    if config.get("state") != "EMAIL_PROVIDER_ACTIVE":
        raise SmtpConfigurationError(
            f"Read-back verification failed: provider {provider_id!r} state is "
            f"{config.get('state')!r}, expected EMAIL_PROVIDER_ACTIVE."
        )
    if not matches_desired(config, desired):
        raise SmtpConfigurationError(
            f"Read-back verification failed: provider {provider_id!r} does not match "
            "the desired SMTP settings after write."
        )


def configure(transport: httpx.BaseTransport | None = None) -> None:
    """`transport` exists only so tests can substitute an in-memory ZITADEL,
    same seam configure_zitadel_login_v2.py's own `configure()` uses --
    never set in real use."""
    zitadel_url = _env("ZITADEL_INTERNAL_URL") or _env("OIDC_ISSUER_URL")
    if not zitadel_url:
        raise SmtpConfigurationError("ZITADEL_INTERNAL_URL (or OIDC_ISSUER_URL) must be set.")

    host = _env("SMTP_HOST")
    if not host:
        print(
            "[configure-smtp] SMTP_HOST is unset -- leaving the existing SMTP "
            "configuration (if any) untouched."
        )
        return

    sender_address = _env("SMTP_SENDER_ADDRESS", DEFAULT_SENDER_ADDRESS)
    assert sender_address is not None
    sender_name = _env("SMTP_SENDER_NAME", DEFAULT_SENDER_NAME)
    assert sender_name is not None
    tls = _bool_env("SMTP_TLS", False)
    reply_to_address = _env("SMTP_REPLY_TO_ADDRESS", "") or ""
    user = _env("SMTP_USER", "") or ""
    password = _env("SMTP_PASSWORD", "") or ""

    pat_path = _env("ZITADEL_BOOTSTRAP_PAT_PATH", DEFAULT_PAT_PATH)
    assert pat_path is not None
    pat = read_pat(pat_path)

    desired = desired_smtp_fields(
        host=host, sender_address=sender_address, sender_name=sender_name, tls=tls
    )

    with httpx.Client(
        base_url=zitadel_url,
        headers={"Authorization": f"Bearer {pat}"},
        timeout=10.0,
        transport=transport,
    ) as client:
        # GetEmailProvider (unlike GetEmailProviderById) only ever returns
        # the currently *active* provider -- ZITADEL's own documented
        # semantics ("Returns the active Email provider from the system").
        # So `existing`, when not None, is always already active; there is
        # no "exists but inactive" case reachable through this endpoint to
        # special-case here.
        existing = get_active_provider(client)

        if existing is not None and matches_desired(existing, desired):
            print(
                f"[configure-smtp] provider {existing['id']!r} already matches the "
                "desired SMTP settings and is active -- no write needed."
            )
            return

        if existing is None:
            print(f"[configure-smtp] adding SMTP provider: host={host!r}")
            provider_id = add_provider(
                client,
                desired=desired,
                reply_to_address=reply_to_address,
                user=user,
                password=password,
            )
        else:
            provider_id = existing["id"]
            print(
                f"[configure-smtp] updating provider {provider_id!r}: "
                f"host {existing.get('smtp', {}).get('host')!r} -> {host!r}"
            )
            update_provider(
                client,
                provider_id,
                desired=desired,
                reply_to_address=reply_to_address,
                user=user,
                password=password,
            )

        activate_provider(client, provider_id)
        verify_active(client, provider_id, desired)
        print(f"[configure-smtp] verified: provider {provider_id!r} is active with host {host!r}.")


def main() -> None:
    try:
        configure()
    except SmtpConfigurationError as exc:
        print(f"[configure-smtp] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
