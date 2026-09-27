"""Marketstack's product-owned custom ZITADEL Login Service
(docs/ADR/0017-product-owned-zitadel-login-service.md).

    GET  /login-svc/login?authRequest=V2_<id>   branded login form
    POST /login-svc/login/password              password (+ user) check
    POST /login-svc/login/totp                  TOTP second-factor check
    GET  /login-svc/login/webauthn/options       WebAuthn challenge (JSON)
    POST /login-svc/login/webauthn/verify        WebAuthn assertion check
    GET  /login-svc/login/forgot-password        request a reset email
    POST /login-svc/login/forgot-password        (same; always a generic response)
    GET  /login-svc/reset-password?userID&code   choose a new password
    POST /login-svc/reset-password               (same; sets the new password)
    POST /login-svc/logout                       this service's own cleanup
    GET  /login-svc/healthz                      liveness

This process never imports SaaS-OS, `product.*`, `core.*`, or `api.*` --
it is a standalone service with its own container boundary. It never
issues a SaaS-OS session, never resolves a tenant, never performs RBAC --
its only output is a browser redirect to the `callback_url` ZITADEL's own
`CreateCallback` returns, which SaaS-OS's existing, unmodified
`/auth/callback` then consumes exactly as it always has (Authorization
Code + PKCE, ID-token validation, `issue_session()`).

Account/password recovery (`UserService.PasswordReset`/`SetPassword`,
`app/zitadel/user_api.py`) is implemented -- previously deferred here
pending a working SMTP configuration, now provided in local development by
`mailpit` + `scripts/configure_zitadel_smtp.py` (docker-compose.yml); any
other environment supplies its own real SMTP provider through the same
`SMTP_*` environment variables. `submit_forgot_password` never reveals
whether the submitted email/username actually resolved to an account --
always the same response either way (account-enumeration prevention).

**Deferred, documented limitations (not implemented here, per ADR-0017's
own non-goals and this task's explicit "stop and report" allowance):**
- External IdP sign-in (`CheckIDPIntent`) -- needs a live-verified
  redirect/callback choreography (`StartIdentityProviderIntent`) this
  audit did not confirm, and the local ZITADEL instance has no IdP
  configured to test against.
- OTP via SMS/Email as a second factor -- see `app/factor_policy.py`'s
  own comment: recognized by ZITADEL, not wired up here.
- New-factor enrollment when a user has zero eligible second factors
  registered but MFA is required -- fails closed with a clear message,
  never silently downgrades to password-only.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app import factor_policy, templates
from app.ceremony import Ceremony, store
from app.config import load_settings
from app.cookies import (
    clear_ceremony_cookie,
    clear_zitadel_session_cookie,
    read_ceremony_cookie,
    read_zitadel_session_cookie,
    set_ceremony_cookie,
    set_zitadel_session_cookie,
)
from app.zitadel import oidc_api, session_api, settings_api, user_api
from app.zitadel.client import ZitadelApiError, ZitadelClient
from app.zitadel.token import ZitadelCredential

logger = logging.getLogger("login_service")

_AUTH_REQUEST_ID_RE = re.compile(r"^V2_[A-Za-z0-9_-]{1,200}$")
# ZITADEL's own validation for both fields is just a length bound (proto:
# user_id min_len 1/max_len 200, verification_code min_len 1/max_len 20) --
# no character-set constraint is documented, so this only narrows to safe
# URL-query characters at the same lengths. Rejecting an obviously-
# malformed value here is defense in depth, not the primary control
# (ZITADEL's own SetPassword call still re-validates both).
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_RESET_CODE_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")
# Sentinel `auth_request_id` for a ceremony that exists only to bind a CSRF
# token to the browser's cookie on the forgot-password/reset-password pages
# -- these never call `_complete()`/`oidc_api.create_callback`, so there is
# no real OIDC `authRequest` to store (docs/ADR/0017's ceremony model was
# designed around the sign-in flow only; reusing it here for CSRF avoids a
# second, parallel piece of state for two simple forms).
_NO_AUTH_REQUEST = ""

# Security audit F-10: a real WebAuthn assertion (authenticatorData +
# clientDataJSON + signature, each base64-encoded, plus a short id/type)
# is at most a few KiB; 16 KiB is generous headroom over that while still
# bounding what an attacker can force this process to buffer before JSON
# parsing even runs.
_WEBAUTHN_MAX_BODY_BYTES = 16 * 1024


async def _read_body_capped(request: Request, *, max_bytes: int) -> bytes | None:
    """Reads the raw request body directly off the ASGI stream, checked
    against actual received bytes as they arrive -- never trusting a
    (possibly absent or understated) Content-Length header alone.
    Returns None, without reading further, the moment the body exceeds
    `max_bytes`."""
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            return None
    return bytes(body)


def _read_private_key(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


settings = load_settings()
_http_client = httpx.Client(timeout=10.0)
_credential = ZitadelCredential(
    issuer=settings.zitadel_issuer,
    user_id=settings.zitadel_service_user_id,
    key_id=settings.zitadel_service_key_id,
    private_key_pem=_read_private_key(settings.zitadel_service_private_key_path),
    http_client=_http_client,
)
zitadel = ZitadelClient(
    base_url=settings.zitadel_issuer, credential=_credential, http_client=_http_client
)

app = FastAPI(title="login-service", docs_url=None, redoc_url=None, openapi_url=None)


def _brand() -> str:
    return settings.brand_name


def _error_response(message: str, *, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(
        templates.render_error_page(brand_name=_brand(), message=message), status_code=status_code
    )


def _safe_redirect(callback_url: str) -> RedirectResponse:
    """`callback_url` comes only from ZITADEL's own verified
    `CreateCallback` response (docs/ADR/0017's open-redirect requirement:
    the browser never supplies a redirect target) -- this is a defense-in-
    depth scheme sanity check, not the primary control."""
    if not (callback_url.startswith("http://") or callback_url.startswith("https://")):
        raise ZitadelApiError(0, "CreateCallback returned a non-http(s) callback_url")
    return RedirectResponse(url=callback_url, status_code=303)


def _load_ceremony(request: Request) -> Ceremony | None:
    ceremony_id = read_ceremony_cookie(request)
    if not ceremony_id:
        return None
    return store.get(ceremony_id)


def _complete(ceremony: Ceremony) -> str:
    """Only ever called after `factor_policy.decide()` reported
    `sufficient=True` against a *fresh* `get_session()` read -- see each
    route below. Consumes the ceremony (single-use)."""
    assert ceremony.session_id and ceremony.session_token
    callback_url = oidc_api.create_callback(
        zitadel,
        auth_request_id=ceremony.auth_request_id,
        session_id=ceremony.session_id,
        session_token=ceremony.session_token,
    )
    store.consume(ceremony.ceremony_id)
    return callback_url


def _evaluate(ceremony: Ceremony) -> factor_policy.Decision:
    # ceremony.session_token is still required overall (CreateCallback
    # needs it below) even though get_session() itself no longer does
    # (security audit F-04 -- see that function's own docstring).
    assert ceremony.session_id and ceremony.session_token
    factors = session_api.get_session(zitadel, session_id=ceremony.session_id)["factors"]
    user_id = factors.get("user", {}).get("id")
    if user_id and not ceremony.user_id:
        store.update(ceremony.ceremony_id, user_id=user_id)
    registered = (
        user_api.list_authentication_method_types(zitadel, user_id=user_id) if user_id else set()
    )
    login_settings = settings_api.get_login_settings(zitadel)
    return factor_policy.decide(
        factors=factors, login_settings=login_settings, registered_methods=registered
    )


@app.get("/login-svc/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/login-svc/login")
def start_login(authRequest: str = "") -> Response:
    if not _AUTH_REQUEST_ID_RE.match(authRequest):
        return _error_response("This sign-in link is invalid.")
    try:
        oidc_api.get_auth_request(zitadel, auth_request_id=authRequest)
    except ZitadelApiError:
        logger.warning("login_svc_auth_request_invalid")
        return _error_response(
            "This sign-in link is invalid or has expired. Please try signing in again."
        )

    ceremony = store.start(authRequest)
    html_body = templates.render_login_page(
        brand_name=_brand(), action="/login-svc/login/password", csrf_token=ceremony.csrf_token
    )
    response = HTMLResponse(html_body)
    set_ceremony_cookie(response, ceremony.ceremony_id, secure=settings.cookie_secure)
    return response


@app.get("/login-svc/login/forgot-password")
def start_forgot_password(request: Request) -> Response:
    # Reuses the in-progress sign-in ceremony's CSRF token/cookie if one is
    # present (the common case: reached via the link on the login page
    # itself); starts a fresh CSRF-only ceremony otherwise (e.g. the
    # sign-in ceremony already expired, or this URL was opened directly).
    ceremony = _load_ceremony(request) or store.start(_NO_AUTH_REQUEST)
    html_body = templates.render_forgot_password_page(
        brand_name=_brand(),
        action="/login-svc/login/forgot-password",
        csrf_token=ceremony.csrf_token,
    )
    response = HTMLResponse(html_body)
    set_ceremony_cookie(response, ceremony.ceremony_id, secure=settings.cookie_secure)
    return response


def _attempt_password_reset(login_name: str) -> None:
    """Best-effort: resolves `login_name` to a user id (via an
    unauthenticated `CreateSession` user-check, the same mechanism
    `submit_password` uses, just without a password check) and requests a
    reset email. Every failure -- unknown user, transport error, ZITADEL
    rejecting the reset itself -- is swallowed here, never surfaced to the
    caller, so the route above always responds identically regardless of
    whether the account exists (account-enumeration prevention, mirroring
    this codebase's existing security posture elsewhere -- see
    `submit_password`'s own F-12 comment for the sibling case this can't
    just reuse, since here even "wrong vs. unknown" must stay
    indistinguishable, not just "wrong password vs. service down")."""
    session_id: str | None = None
    session_token: str | None = None
    try:
        created = session_api.create_session(zitadel, login_name=login_name)
        session_id = created.get("sessionId")
        session_token = created.get("sessionToken")
        if not session_id:
            return
        session = session_api.get_session(zitadel, session_id=session_id)
        user_id = session.get("factors", {}).get("user", {}).get("id")
        if not user_id:
            return
        url_template = (
            f"{settings.public_login_service_origin}/login-svc/reset-password"
            "?userID={{.UserID}}&code={{.Code}}"
        )
        user_api.password_reset(zitadel, user_id=user_id, url_template=url_template)
    except ZitadelApiError:
        logger.info("login_svc_forgot_password_attempt_failed")
    finally:
        if session_id:
            try:
                session_api.delete_session(
                    client=zitadel, session_id=session_id, session_token=session_token
                )
            except ZitadelApiError:
                pass


@app.post("/login-svc/login/forgot-password")
def submit_forgot_password(
    request: Request, csrf_token: str = Form(...), login_name: str = Form(...)
) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None or not store.verify_csrf(ceremony, csrf_token):
        return _error_response("Your session has expired. Please try again.")

    _attempt_password_reset(login_name)
    return HTMLResponse(templates.render_forgot_password_sent_page(brand_name=_brand()))


@app.get("/login-svc/reset-password")
def start_reset_password(request: Request, userID: str = "", code: str = "") -> Response:
    if not _USER_ID_RE.match(userID) or not _RESET_CODE_RE.match(code):
        return _error_response("This password reset link is invalid.")

    ceremony = _load_ceremony(request) or store.start(_NO_AUTH_REQUEST)
    html_body = templates.render_reset_password_page(
        brand_name=_brand(),
        action="/login-svc/reset-password",
        csrf_token=ceremony.csrf_token,
        user_id=userID,
        code=code,
    )
    response = HTMLResponse(html_body)
    set_ceremony_cookie(response, ceremony.ceremony_id, secure=settings.cookie_secure)
    return response


@app.post("/login-svc/reset-password")
def submit_reset_password(
    request: Request,
    csrf_token: str = Form(...),
    user_id: str = Form(...),
    code: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None or not store.verify_csrf(ceremony, csrf_token):
        return _error_response("Your session has expired. Please try again.")
    if not _USER_ID_RE.match(user_id) or not _RESET_CODE_RE.match(code):
        return _error_response("This password reset link is invalid.")

    def _retry(error: str) -> HTMLResponse:
        return HTMLResponse(
            templates.render_reset_password_page(
                brand_name=_brand(),
                action="/login-svc/reset-password",
                csrf_token=ceremony.csrf_token,
                user_id=user_id,
                code=code,
                error=error,
            )
        )

    if password != password_confirm:
        return _retry("Those passwords do not match.")

    try:
        user_api.set_password(zitadel, user_id=user_id, password=password, verification_code=code)
    except ZitadelApiError:
        return _retry(
            "Could not reset your password. The link may have expired, or the new "
            "password does not meet the requirements. Please try again."
        )

    store.consume(ceremony.ceremony_id)
    response = HTMLResponse(templates.render_reset_password_done_page(brand_name=_brand()))
    clear_ceremony_cookie(response, secure=settings.cookie_secure)
    return response


def _render_next_step(
    ceremony: Ceremony, decision: factor_policy.Decision, *, error: str | None = None
) -> HTMLResponse:
    if decision.reason == "mfa_unavailable":
        return _error_response(
            "Additional verification is required for this account, but no supported "
            "method is registered. Contact your administrator."
        )
    if decision.next_factor == "totp":
        store.update(ceremony.ceremony_id, pending_factor="totp")
        return HTMLResponse(
            templates.render_totp_page(
                brand_name=_brand(),
                action="/login-svc/login/totp",
                csrf_token=ceremony.csrf_token,
                error=error,
            )
        )
    if decision.next_factor == "webAuthN":
        store.update(ceremony.ceremony_id, pending_factor="webAuthN")
        return HTMLResponse(
            templates.render_webauthn_page(
                brand_name=_brand(),
                csrf_token=ceremony.csrf_token,
                options_url="/login-svc/login/webauthn/options",
                verify_url="/login-svc/login/webauthn/verify",
                error=error,
            )
        )
    return _error_response("Invalid email or password.")


@app.post("/login-svc/login/password")
def submit_password(
    request: Request,
    csrf_token: str = Form(...),
    login_name: str = Form(...),
    password: str = Form(...),
) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None:
        return _error_response("Your sign-in session has expired. Please try signing in again.")
    if not store.verify_csrf(ceremony, csrf_token):
        logger.warning("login_svc_csrf_mismatch")
        return _error_response("Your sign-in session has expired. Please try signing in again.")

    try:
        created = session_api.create_session(zitadel, login_name=login_name, password=password)
    except ZitadelApiError as exc:
        # Security audit F-12: an actual authentication rejection (ZITADEL
        # CreateSession's own verified status for a wrong password/unknown
        # user, live-verified elsewhere in this codebase as 401) keeps the
        # existing generic message -- unchanged, and still never
        # distinguishes unknown-user from wrong-password. Any other status
        # (a ZITADEL service failure, or `0` for a transport-level
        # failure -- see app/zitadel/client.py's own ZitadelApiError call
        # sites) means this service could not actually evaluate the
        # credential at all, which is a different, non-security-sensitive
        # fact worth surfacing distinctly -- never the status code,
        # reason, or any other exception detail.
        error_message = (
            "Invalid email or password."
            if exc.status_code == 401
            else "Authentication service temporarily unavailable. Please try again."
        )
        return HTMLResponse(
            templates.render_login_page(
                brand_name=_brand(),
                action="/login-svc/login/password",
                csrf_token=ceremony.csrf_token,
                error=error_message,
            )
        )

    store.update(
        ceremony.ceremony_id,
        session_id=created["sessionId"],
        session_token=created["sessionToken"],
        login_name=login_name,
    )
    ceremony = store.get(ceremony.ceremony_id)
    assert ceremony is not None

    decision = _evaluate(ceremony)
    if decision.sufficient:
        callback_url = _complete(ceremony)
        return _finish_success(_safe_redirect(callback_url), ceremony)

    return _render_next_step(ceremony, decision)


def _finish_success(response: RedirectResponse, ceremony: Ceremony) -> RedirectResponse:
    assert ceremony.session_id
    set_zitadel_session_cookie(response, ceremony.session_id, secure=settings.cookie_secure)
    clear_ceremony_cookie(response, secure=settings.cookie_secure)
    return response


@app.post("/login-svc/login/totp")
def submit_totp(request: Request, csrf_token: str = Form(...), code: str = Form(...)) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None or ceremony.pending_factor != "totp" or not ceremony.session_id:
        return _error_response("Your sign-in session has expired. Please try signing in again.")
    if not store.verify_csrf(ceremony, csrf_token):
        return _error_response("Your sign-in session has expired. Please try signing in again.")

    try:
        updated = session_api.set_session(
            zitadel,
            session_id=ceremony.session_id,
            session_token=ceremony.session_token,
            totp_code=code,
        )
    except ZitadelApiError:
        return HTMLResponse(
            templates.render_totp_page(
                brand_name=_brand(),
                action="/login-svc/login/totp",
                csrf_token=ceremony.csrf_token,
                error="That code was not correct. Please try again.",
            )
        )

    store.update(ceremony.ceremony_id, session_token=updated["sessionToken"])
    ceremony = store.get(ceremony.ceremony_id)
    assert ceremony is not None

    decision = _evaluate(ceremony)
    if decision.sufficient:
        callback_url = _complete(ceremony)
        return _finish_success(_safe_redirect(callback_url), ceremony)
    return _render_next_step(
        ceremony, decision, error="That code was not correct. Please try again."
    )


@app.get("/login-svc/login/webauthn/options")
def webauthn_options(request: Request) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None or ceremony.pending_factor != "webAuthN" or not ceremony.session_id:
        return JSONResponse({"error": "invalid_ceremony"}, status_code=400)

    domain = httpx.URL(settings.public_login_service_origin).host
    try:
        updated = session_api.set_session(
            zitadel,
            session_id=ceremony.session_id,
            session_token=ceremony.session_token,
            request_webauthn_challenge={
                "domain": domain,
                "userVerificationRequirement": "REQUIRED",
            },
        )
    except ZitadelApiError:
        return JSONResponse({"error": "challenge_unavailable"}, status_code=502)

    store.update(ceremony.ceremony_id, session_token=updated["sessionToken"])
    options = (
        updated.get("challenges", {}).get("webAuthN", {}).get("publicKeyCredentialRequestOptions")
    )
    if not options:
        return JSONResponse({"error": "challenge_unavailable"}, status_code=502)
    return JSONResponse(options)


@app.post("/login-svc/login/webauthn/verify")
async def webauthn_verify(request: Request) -> Response:
    ceremony = _load_ceremony(request)
    if ceremony is None or ceremony.pending_factor != "webAuthN" or not ceremony.session_id:
        return JSONResponse({"error": "Your sign-in session has expired."}, status_code=400)
    if not store.verify_csrf(ceremony, request.headers.get("x-ceremony-csrf")):
        return JSONResponse({"error": "Your sign-in session has expired."}, status_code=400)

    raw_body = await _read_body_capped(request, max_bytes=_WEBAUTHN_MAX_BODY_BYTES)
    if raw_body is None:
        return JSONResponse({"error": "Request too large."}, status_code=413)
    assertion = json.loads(raw_body)
    try:
        updated = session_api.set_session(
            zitadel,
            session_id=ceremony.session_id,
            session_token=ceremony.session_token,
            webauthn_assertion=assertion,
        )
    except ZitadelApiError:
        return JSONResponse({"error": "Verification failed."}, status_code=400)

    store.update(ceremony.ceremony_id, session_token=updated["sessionToken"])
    ceremony = store.get(ceremony.ceremony_id)
    assert ceremony is not None

    decision = _evaluate(ceremony)
    if not decision.sufficient:
        return JSONResponse({"error": "Verification failed."}, status_code=400)

    callback_url = _complete(ceremony)
    response = JSONResponse({"redirect": callback_url})
    set_zitadel_session_cookie(response, ceremony.session_id, secure=settings.cookie_secure)
    clear_ceremony_cookie(response, secure=settings.cookie_secure)
    return response


@app.post("/login-svc/logout")
def logout(request: Request) -> Response:
    """This service's own cleanup step -- does NOT touch SaaS-OS's
    `/auth/logout` (unchanged, called separately by the product frontend).
    Deleting the underlying ZITADEL Session API object here (rather than
    letting it merely expire) is what "provider-session termination"
    means in this architecture -- there is no ZITADEL browser cookie to
    clear (the browser never visits a ZITADEL-hosted page in this flow at
    all)."""
    session_id = read_zitadel_session_cookie(request)
    if session_id:
        try:
            session_api.delete_session(zitadel, session_id=session_id, session_token=None)
        except ZitadelApiError:
            logger.warning("login_svc_logout_delete_session_failed")
    response = Response(status_code=204)
    clear_zitadel_session_cookie(response, secure=settings.cookie_secure)
    clear_ceremony_cookie(response, secure=settings.cookie_secure)
    return response
