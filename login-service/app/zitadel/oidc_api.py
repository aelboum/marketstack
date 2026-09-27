"""`zitadel.oidc.v2.OIDCService` -- verified against
`proto/zitadel/oidc/v2/oidc_service.proto` + `authorization.proto`
(tag v4.19.0):

    GetAuthRequest   GET  /v2/oidc/auth_requests/{auth_request_id}   permission session.read
    CreateCallback   POST /v2/oidc/auth_requests/{auth_request_id}   permission session.link

`GetAuthRequest`'s response carries the OIDC client/scope/redirect
context ZITADEL itself already validated -- it carries NO MFA/factor
policy field (confirmed by direct proto inspection: `AuthRequest` has no
such field). Policy comes only from `settings_api.get_login_settings()`.

`CreateCallback`'s own response `callback_url` is, per its proto comment,
"credentials" in effect (it embeds a usable authorization code) -- this
service treats it exactly as such: it is only ever used as an HTTP
redirect Location for the current browser response, never logged, never
returned as JSON, never otherwise persisted.
"""

from __future__ import annotations

from app.zitadel.client import ZitadelClient


def get_auth_request(client: ZitadelClient, *, auth_request_id: str) -> dict:
    body = client.request("GET", f"/v2/oidc/auth_requests/{auth_request_id}")
    return body.get("authRequest", body)


def create_callback(
    client: ZitadelClient, *, auth_request_id: str, session_id: str, session_token: str
) -> str:
    """Returns the callback URL to redirect the browser to. Callers MUST
    have already established (via `app/factor_policy.py`, against a fresh
    `session_api.get_session()` read) that the session satisfies the
    required authentication policy -- this function performs no such
    check itself, matching the verified fact that `CreateCallback` does
    not either (docs/ADR/0017's own Security requirements)."""
    body = client.request(
        "POST",
        f"/v2/oidc/auth_requests/{auth_request_id}",
        json={"session": {"sessionId": session_id, "sessionToken": session_token}},
    )
    callback_url = body.get("callbackUrl")
    if not isinstance(callback_url, str) or not callback_url:
        raise ValueError("CreateCallback response carried no callbackUrl")
    return callback_url
