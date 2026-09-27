"""This service's own cookie namespace -- entirely separate from SaaS-OS's
`product_session`/`product_session_login` (never reused, never imported).

Both cookies below are scoped `Path=/login-svc`: per RFC 6265 SS5.1.4, a
cookie's Path attribute is a browser-enforced prefix match against the
request path -- a cookie set with `Path=/login-svc` is never attached to a
request whose path is `/auth/*` or `/v1/*` on the same origin. This is the
cookie-isolation mechanism docs/ADR/0017 requires; it needs no Caddy-side
stripping because the browser itself never sends the cookie there in the
first place.
"""

from __future__ import annotations

from fastapi import Request, Response

from app.ceremony import CEREMONY_COOKIE_NAME, CEREMONY_COOKIE_PATH, CEREMONY_TTL_SECONDS

ZITADEL_SESSION_COOKIE_NAME = "login_svc_zitadel_session"
ZITADEL_SESSION_COOKIE_MAX_AGE_SECONDS = 12 * 60 * 60  # matches SaaS-OS's own session lifetime


def set_ceremony_cookie(response: Response, ceremony_id: str, *, secure: bool) -> None:
    response.set_cookie(
        key=CEREMONY_COOKIE_NAME,
        value=ceremony_id,
        max_age=CEREMONY_TTL_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=CEREMONY_COOKIE_PATH,
    )


def read_ceremony_cookie(request: Request) -> str | None:
    return request.cookies.get(CEREMONY_COOKIE_NAME)


def clear_ceremony_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=CEREMONY_COOKIE_NAME,
        path=CEREMONY_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def set_zitadel_session_cookie(response: Response, session_id: str, *, secure: bool) -> None:
    """Set once, at the moment `CreateCallback` succeeds -- lets a later
    `/login-svc/logout` call find and delete the underlying ZITADEL
    Session API object. Holds only the session_id (never the session
    token) -- this service's own privileged credential already has
    `session.delete`, so presenting the token is not required."""
    response.set_cookie(
        key=ZITADEL_SESSION_COOKIE_NAME,
        value=session_id,
        max_age=ZITADEL_SESSION_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path=CEREMONY_COOKIE_PATH,
    )


def read_zitadel_session_cookie(request: Request) -> str | None:
    return request.cookies.get(ZITADEL_SESSION_COOKIE_NAME)


def clear_zitadel_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        key=ZITADEL_SESSION_COOKIE_NAME,
        path=CEREMONY_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="lax",
    )
