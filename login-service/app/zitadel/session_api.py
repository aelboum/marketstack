"""`zitadel.session.v2.SessionService` -- verified against
`proto/zitadel/session/v2/session_service.proto` +
`proto/zitadel/session/v2/session.proto` (tag v4.19.0):

    CreateSession   POST   /v2/sessions                    permission session.write
    SetSession      PATCH  /v2/sessions/{session_id}        permission session.write
    GetSession      GET    /v2/sessions/{session_id}        permission session.read
    DeleteSession   DELETE /v2/sessions/{session_id}        permission session.delete

`CreateSession`/`SetSession` responses carry only `sessionId`/
`sessionToken`/`challenges` -- NOT the resulting `factors`. Reading which
factors are actually verified always requires a separate `GetSession`
call (this is deliberate on ZITADEL's part, not an oversight here) --
`app/factor_policy.py` is the module that decides what those factors mean
security-wise; this module only transports data.
"""

from __future__ import annotations

from app.zitadel.client import ZitadelClient


def create_session(
    client: ZitadelClient,
    *,
    login_name: str | None = None,
    password: str | None = None,
    request_webauthn_challenge: dict | None = None,
) -> dict:
    checks: dict = {}
    if login_name is not None:
        checks["user"] = {"loginName": login_name}
    if password is not None:
        checks["password"] = {"password": password}
    body: dict = {"checks": checks}
    if request_webauthn_challenge is not None:
        body["challenges"] = {"webAuthN": request_webauthn_challenge}
    return client.request("POST", "/v2/sessions", json=body)


def set_session(
    client: ZitadelClient,
    *,
    session_id: str,
    session_token: str,
    totp_code: str | None = None,
    otp_sms_code: str | None = None,
    otp_email_code: str | None = None,
    webauthn_assertion: dict | None = None,
    request_webauthn_challenge: dict | None = None,
) -> dict:
    checks: dict = {}
    if totp_code is not None:
        checks["totp"] = {"code": totp_code}
    if otp_sms_code is not None:
        checks["otpSms"] = {"code": otp_sms_code}
    if otp_email_code is not None:
        checks["otpEmail"] = {"code": otp_email_code}
    if webauthn_assertion is not None:
        checks["webAuthN"] = {"credentialAssertionData": webauthn_assertion}
    body: dict = {"sessionToken": session_token}
    if checks:
        body["checks"] = checks
    if request_webauthn_challenge is not None:
        body["challenges"] = {"webAuthN": request_webauthn_challenge}
    return client.request("PATCH", f"/v2/sessions/{session_id}", json=body)


def get_session(client: ZitadelClient, *, session_id: str) -> dict:
    """Returns the `Session` object (unwrapped from any `{"session": ...}`
    envelope) -- specifically its `factors`, the ground truth
    `app/factor_policy.py` reasons over.

    Security audit F-04: `GetSession`'s own permission model is
    `session.read` OR presenting the session's own token (verified proto
    comment: the token requirement is "waived for own sessions or when
    the session token itself is presented"). This service's runtime
    credential already holds `session.read` unconditionally, as part of
    the `IAM_LOGIN_CLIENT` role every other call in this module already
    relies on -- so the token is never sent here at all, live-verified
    against the pinned ZITADEL v4.19.0 instance (a real GetSession with
    no `sessionToken` query parameter returns the identical `factors`
    payload as one that includes it). This does not change the ZITADEL
    API contract -- same endpoint, same method, same permission the
    credential already had -- it only stops transmitting a bearer-
    equivalent value this specific call never needed, which removes the
    URL-query-parameter exposure surface for `GetSession` entirely rather
    than merely trying to redact it after the fact. `CreateCallback`
    (app/zitadel/oidc_api.py) still requires and receives the token
    separately -- proof of possession is genuinely required there, and is
    unaffected by this change."""
    body = client.request("GET", f"/v2/sessions/{session_id}")
    return body.get("session", body)


def delete_session(client: ZitadelClient, *, session_id: str, session_token: str | None) -> None:
    params = {"sessionToken": session_token} if session_token else None
    client.request("DELETE", f"/v2/sessions/{session_id}", params=params)
