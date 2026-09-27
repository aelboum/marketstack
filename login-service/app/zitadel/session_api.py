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


def get_session(client: ZitadelClient, *, session_id: str, session_token: str) -> dict:
    """Returns the `Session` object (unwrapped from any `{"session": ...}`
    envelope) -- specifically its `factors`, the ground truth
    `app/factor_policy.py` reasons over.

    `sessionToken` travels as a query parameter, not a JSON body: a GET
    request's `google.api.http` mapping (no `body: "*"` on this RPC) puts
    every non-path request field on the query string, per grpc-gateway's
    own convention -- mirrors every other GET in this codebase's verified
    ZITADEL calls (e.g. ListApplications' own filters are the one
    documented exception, sent as a POST)."""
    body = client.request(
        "GET", f"/v2/sessions/{session_id}", params={"sessionToken": session_token}
    )
    return body.get("session", body)


def delete_session(client: ZitadelClient, *, session_id: str, session_token: str | None) -> None:
    params = {"sessionToken": session_token} if session_token else None
    client.request("DELETE", f"/v2/sessions/{session_id}", params=params)
