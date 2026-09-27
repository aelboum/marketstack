"""Marketstack's product-owned custom ZITADEL Login Service
(docs/ADR/0017-product-owned-zitadel-login-service.md).

    GET  /login-svc/login?authRequest=V2_<id>   branded login form
    POST /login-svc/login/password              password (+ user) check
    POST /login-svc/login/totp                  TOTP second-factor check
    GET  /login-svc/login/webauthn/options       WebAuthn challenge (JSON)
    POST /login-svc/login/webauthn/verify        WebAuthn assertion check
    POST /login-svc/logout                       this service's own cleanup
    GET  /login-svc/healthz                      liveness

This process never imports SaaS-OS, `product.*`, `core.*`, or `api.*` --
it is a standalone service with its own container boundary. It never
issues a SaaS-OS session, never resolves a tenant, never performs RBAC --
its only output is a browser redirect to the `callback_url` ZITADEL's own
`CreateCallback` returns, which SaaS-OS's existing, unmodified
`/auth/callback` then consumes exactly as it always has (Authorization
Code + PKCE, ID-token validation, `issue_session()`).

**Deferred, documented limitations (not implemented here, per ADR-0017's
own non-goals and this task's explicit "stop and report" allowance):**
- External IdP sign-in (`CheckIDPIntent`) -- needs a live-verified
  redirect/callback choreography (`StartIdentityProviderIntent`) this
  audit did not confirm, and the local ZITADEL instance has no IdP
  configured to test against.
- Account/password recovery -- `UserService.PasswordReset`/`UpdateUser`
  are real, verified, self-service-capable APIs, but wiring them up needs
  a verified working SMTP configuration on this ZITADEL instance, which
  is out of this task's scope to provision. The UI states the limitation
  rather than offering a broken link.
- OTP via SMS/Email as a second factor -- see `app/factor_policy.py`'s
  own comment: recognized by ZITADEL, not wired up here.
- New-factor enrollment when a user has zero eligible second factors
  registered but MFA is required -- fails closed with a clear message,
  never silently downgrades to password-only.
"""

from __future__ import annotations

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
    except ZitadelApiError:
        return HTMLResponse(
            templates.render_login_page(
                brand_name=_brand(),
                action="/login-svc/login/password",
                csrf_token=ceremony.csrf_token,
                error="Invalid email or password.",
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

    assertion = await request.json()
    try:
        updated = session_api.set_session(
            zitadel, session_id=ceremony.session_id, session_token=ceremony.session_token,
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
