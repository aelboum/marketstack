"""Marketstack-owned post-bootstrap ZITADEL Login V2 configuration
(docs/ADR/0017-product-owned-zitadel-login-service.md).

`saas-os-local-identity` (the installed `saas-os` dependency's own
bootstrap tool, `infra/local_identity/zitadel_bootstrap.py`) creates the
`product`/`product-backend` OIDC application but never sets
`loginVersion` on it -- verified against the pinned saas-os commit: its
own `application_request()` builds only `redirectUris`/`responseTypes`/
`grantTypes`/`applicationType`/`authMethodType`. This script is the
narrow, Marketstack-owned step that runs *after* that bootstrap and sets
exactly one field:

    zitadel.application.v2.ApplicationService.UpdateApplication
        oidc_configuration.login_version.login_v2.base_uri

Nothing else on the application is read, sent, or changed -- every other
`UpdateOIDCApplicationConfigurationRequest` field is left absent from the
request body, which ZITADEL's own documented semantics ("If not set, X
will not be changed") leaves untouched.

Deterministic targeting: the application is resolved by
`OIDC_CLIENT_ID` (the same value the running backend itself uses to talk
to ZITADEL) *within* the project named `OIDC_LOCAL_PROJECT_NAME` -- never
by display name alone, never "first match". Any ambiguity (zero or more
than one project/application matching) aborts with no write. This also
means the unrelated `Marketstack Custom Login Verification` test project
can never be touched here: its application's `client_id` is not
`OIDC_CLIENT_ID`.

Configuration (environment variables):

- `ZITADEL_INTERNAL_URL` (or `OIDC_ISSUER_URL` as a fallback -- both
  already point at the same local ZITADEL instance in this topology):
  required.
- `ZITADEL_BOOTSTRAP_PAT_PATH` (default `/bootstrap/bootstrap.pat`) --
  the *same* bootstrap machine-user PAT `saas-os-local-identity` itself
  already uses. This is explicitly a LOCAL/BOOTSTRAP credential
  (IAM_OWNER-scoped), reused here only because it is the one
  configuration-capable credential this local topology already has --
  never the credential the future Login service uses for the Session
  API (ADR-0017's security requirements keep those two authorities
  separate).
- `OIDC_LOCAL_PROJECT_NAME` (default `product`), `OIDC_CLIENT_ID`
  (required) -- resolve the target application.
- `OIDC_LOCAL_APPLICATION_NAME` (optional) -- if set, the resolved
  application's own name must match it exactly, or the run aborts.
- `ZITADEL_LOGIN_V2_BASE_URI` -- the desired
  `loginVersion.loginV2.baseUri`. Unset/empty: a safe no-op -- whatever
  is currently configured (including "nothing") is left exactly as is.
  Set: the application is updated to match exactly (skipped if it
  already does), and the write is read back and verified before this
  script reports success.

Never logs, prints, or raises with the PAT value in it.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

DEFAULT_PAT_PATH = "/bootstrap/bootstrap.pat"
DEFAULT_PROJECT_NAME = "product"

_RETRIES = 15
_RETRY_DELAY_SECONDS = 2.0


class LoginV2ConfigurationError(RuntimeError):
    """Raised for any failure in this script. Never carries the PAT or any
    request header -- every message here is built from non-secret values
    only (ids, names, URIs)."""


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
        raise LoginV2ConfigurationError(
            f"Could not read the bootstrap PAT from {path!r}: {type(exc).__name__}. "
            "Has the zitadel-bootstrap (saas-os-local-identity) step completed?"
        ) from None


def _call(client: httpx.Client, method: str, path: str, json: dict | None = None) -> dict:
    """Retried request. Only the exception *type* is ever reported (never
    `str(exc)`) -- httpx does not put the Authorization header value into
    its own exception messages, but nothing here relies on that."""
    last_error: Exception | None = None
    for attempt in range(1, _RETRIES + 1):
        try:
            response = client.request(method, path, json=json)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            last_error = exc
            print(
                f"[configure-login-v2] {method} {path} failed "
                f"(attempt {attempt}/{_RETRIES}): {type(exc).__name__}",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY_SECONDS)
    raise LoginV2ConfigurationError(
        f"{method} {path} failed after {_RETRIES} attempts ({type(last_error).__name__})"
    ) from None


def get_org_id(client: httpx.Client) -> str:
    body = _call(client, "GET", "/management/v1/orgs/me")
    return body["org"]["id"]


def find_project(client: httpx.Client, org_id: str, project_name: str) -> str:
    listing = _call(
        client,
        "POST",
        "/zitadel.project.v2.ProjectService/ListProjects",
        json={"filters": [{"organizationIdFilter": {"organizationId": org_id}}]},
    )
    matches = [p for p in listing.get("projects", []) if p.get("name") == project_name]
    if len(matches) != 1:
        raise LoginV2ConfigurationError(
            f"Expected exactly one project named {project_name!r} in org {org_id!r}, "
            f"found {len(matches)}. Refusing to guess."
        )
    return matches[0]["projectId"]


def find_application(
    client: httpx.Client,
    project_id: str,
    client_id: str,
    expected_name: str | None,
) -> dict:
    listing = _call(
        client,
        "POST",
        "/zitadel.application.v2.ApplicationService/ListApplications",
        json={"filters": [{"projectIdFilter": {"projectId": project_id}}]},
    )
    apps = listing.get("applications", [])
    matches = [a for a in apps if a.get("oidcConfiguration", {}).get("clientId") == client_id]
    if len(matches) != 1:
        raise LoginV2ConfigurationError(
            f"Expected exactly one application with client_id {client_id!r} in project "
            f"{project_id!r}, found {len(matches)}. Refusing to guess."
        )
    app = matches[0]
    if app.get("projectId") != project_id:
        raise LoginV2ConfigurationError(
            "Resolved application's own projectId does not match the project it was "
            "listed under. Refusing to update."
        )
    if expected_name is not None and app.get("name") != expected_name:
        raise LoginV2ConfigurationError(
            f"Resolved application name {app.get('name')!r} does not match expected "
            f"{expected_name!r}. Refusing to update."
        )
    return app


def current_base_uri(app: dict) -> str | None:
    login_version = app.get("oidcConfiguration", {}).get("loginVersion") or {}
    login_v2 = login_version.get("loginV2")
    if not login_v2:
        return None
    return login_v2.get("baseUri") or None


def update_base_uri(
    client: httpx.Client, application_id: str, project_id: str, base_uri: str
) -> None:
    """Sends only `oidcConfiguration.loginVersion` -- no other field is
    present in the request body, so every other existing setting
    (redirect URIs, grant/response types, application type, auth method,
    ...) is left exactly as ZITADEL already has it."""
    _call(
        client,
        "POST",
        "/zitadel.application.v2.ApplicationService/UpdateApplication",
        json={
            "applicationId": application_id,
            "projectId": project_id,
            "oidcConfiguration": {"loginVersion": {"loginV2": {"baseUri": base_uri}}},
        },
    )


def verify_base_uri(
    client: httpx.Client, project_id: str, application_id: str, expected: str
) -> None:
    listing = _call(
        client,
        "POST",
        "/zitadel.application.v2.ApplicationService/ListApplications",
        json={"filters": [{"projectIdFilter": {"projectId": project_id}}]},
    )
    apps = [a for a in listing.get("applications", []) if a.get("applicationId") == application_id]
    if len(apps) != 1:
        raise LoginV2ConfigurationError(
            "Read-back after update did not find exactly one matching application."
        )
    actual = current_base_uri(apps[0])
    if actual != expected:
        raise LoginV2ConfigurationError(
            f"Read-back verification failed: loginVersion.loginV2.baseUri is {actual!r}, "
            f"expected {expected!r}."
        )


def configure(transport: httpx.BaseTransport | None = None) -> None:
    """`transport` exists only so tests can substitute an in-memory ZITADEL
    (mirrors saas-os's own `infra.local_identity.zitadel_bootstrap.bootstrap`
    test seam) -- never set in real use."""
    zitadel_url = _env("ZITADEL_INTERNAL_URL") or _env("OIDC_ISSUER_URL")
    if not zitadel_url:
        raise LoginV2ConfigurationError("ZITADEL_INTERNAL_URL (or OIDC_ISSUER_URL) must be set.")

    client_id = _env("OIDC_CLIENT_ID")
    if not client_id:
        raise LoginV2ConfigurationError(
            "OIDC_CLIENT_ID must be set -- it is how the target application is resolved "
            "deterministically."
        )

    desired_base_uri = _env("ZITADEL_LOGIN_V2_BASE_URI")
    if desired_base_uri is None:
        print(
            "[configure-login-v2] ZITADEL_LOGIN_V2_BASE_URI is unset -- leaving the "
            "existing Login V2 configuration (if any) untouched."
        )
        return

    pat_path = _env("ZITADEL_BOOTSTRAP_PAT_PATH", DEFAULT_PAT_PATH)
    assert pat_path is not None
    project_name = _env("OIDC_LOCAL_PROJECT_NAME", DEFAULT_PROJECT_NAME)
    assert project_name is not None
    application_name = _env("OIDC_LOCAL_APPLICATION_NAME")

    pat = read_pat(pat_path)
    with httpx.Client(
        base_url=zitadel_url,
        headers={"Authorization": f"Bearer {pat}"},
        timeout=10.0,
        transport=transport,
    ) as client:
        org_id = get_org_id(client)
        project_id = find_project(client, org_id, project_name)
        app = find_application(client, project_id, client_id, application_name)
        application_id = app["applicationId"]

        existing_base_uri = current_base_uri(app)
        if existing_base_uri == desired_base_uri:
            print(
                f"[configure-login-v2] application {application_id!r} already has "
                f"loginVersion.loginV2.baseUri = {desired_base_uri!r} -- no write needed."
            )
            return

        print(
            f"[configure-login-v2] updating application {application_id!r}: "
            f"loginVersion.loginV2.baseUri {existing_base_uri!r} -> {desired_base_uri!r}"
        )
        update_base_uri(client, application_id, project_id, desired_base_uri)
        verify_base_uri(client, project_id, application_id, desired_base_uri)
        print(
            f"[configure-login-v2] verified: loginVersion.loginV2.baseUri == "
            f"{desired_base_uri!r} on application {application_id!r}."
        )


def main() -> None:
    try:
        configure()
    except LoginV2ConfigurationError as exc:
        print(f"[configure-login-v2] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
