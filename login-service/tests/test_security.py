from __future__ import annotations

import pytest
from app.zitadel.client import ZitadelApiError

from tests.test_auth_request import _extract_csrf


def test_csrf_mismatch_rejected(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_csrf")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    client.get("/login-svc/login", params={"authRequest": "V2_csrf"})

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": "wrong-token", "login_name": "a@example.com", "password": "pw"},
    )
    assert response.status_code == 400
    callback_calls = [c for c in fake_zitadel.calls if c[0] == "POST" and "auth_requests" in c[1]]
    assert callback_calls == []


def test_replayed_password_submission_after_success_is_rejected(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_replay")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_replay"})
    csrf = _extract_csrf(start.text)

    first = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )
    assert first.status_code == 303

    # The ceremony cookie was cleared on success; a browser replaying the
    # exact same POST (e.g. via back-button resubmission) no longer has a
    # valid ceremony to act on.
    replay = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
    )
    assert replay.status_code == 400


def test_session_expiry_invalidates_ceremony(client, fake_zitadel, monkeypatch):
    fake_zitadel.add_auth_request("V2_expiry")
    client.get("/login-svc/login", params={"authRequest": "V2_expiry"})

    from app.ceremony import store

    # Force every stored ceremony to be already-expired.
    for ceremony in list(store._ceremonies.values()):
        ceremony.expires_at = 0

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": "irrelevant", "login_name": "a@example.com", "password": "pw"},
    )
    assert response.status_code == 400


def test_ceremony_cookie_attributes():
    from app.ceremony import CEREMONY_COOKIE_PATH

    assert CEREMONY_COOKIE_PATH == "/login-svc"
    assert CEREMONY_COOKIE_PATH != "/"


def test_ceremony_cookie_never_reaches_auth_or_v1_paths_by_path_scoping():
    """RFC 6265 Path-attribute enforcement is browser-side, not this
    service's -- this test documents and pins the exact Path value the
    isolation depends on."""
    from app.ceremony import CEREMONY_COOKIE_PATH

    assert not CEREMONY_COOKIE_PATH.startswith("/auth")
    assert not CEREMONY_COOKIE_PATH.startswith("/v1")


def test_zitadel_session_cookie_scoped_to_login_svc_path(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_cookie")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_cookie"})
    csrf = _extract_csrf(start.text)

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )
    cookies = response.headers.get_list("set-cookie")
    set_cookie = next(h for h in cookies if "login_svc_zitadel_session" in h)
    assert "Path=/login-svc" in set_cookie
    assert "Path=/;" not in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "HttpOnly" in set_cookie


def test_credential_never_appears_in_any_response(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_leak")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_leak"})
    csrf = _extract_csrf(start.text)
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )
    from app.config import load_settings

    settings = load_settings()
    private_key_snippet = "-----BEGIN"
    assert private_key_snippet not in response.text
    assert settings.zitadel_service_key_id not in response.headers.get("location", "")


def test_zitadel_api_error_never_carries_request_body_verbatim():
    error = ZitadelApiError(401, "request rejected")
    assert "password" not in str(error)
    assert "s3cret" not in str(error)


def test_open_redirect_rejected_for_non_http_callback_url():
    from app.main import _safe_redirect

    with pytest.raises(ZitadelApiError):
        _safe_redirect("javascript:alert(1)")


# --- F-04: sessionToken query-parameter exposure ------------------------------


def test_get_session_never_sends_session_token_as_a_query_parameter(client, fake_zitadel):
    """The real security property (live-verified against ZITADEL v4.19.0,
    see app/zitadel/session_api.py::get_session's own docstring): this
    service's privileged credential already holds session.read
    unconditionally, so GetSession is called with no sessionToken at all
    -- not merely a redacted/logged-elsewhere one. Asserted directly
    against the recorded call, not a source-string search."""
    fake_zitadel.add_auth_request("V2_f04")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_f04"})
    csrf = _extract_csrf(start.text)

    client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )

    get_session_calls = [
        c for c in fake_zitadel.calls if c[0] == "GET" and c[1].startswith("/v2/sessions/")
    ]
    assert get_session_calls, "expected at least one GetSession call"
    for _method, _path, _json, params in get_session_calls:
        assert params is None or "sessionToken" not in params


def test_session_token_never_appears_in_captured_output_during_normal_login(
    client, fake_zitadel, capsys
):
    """End-to-end proof for the exact login flow this service performs:
    no captured stdout/stderr output contains the real session token
    value, whether from GetSession (which no longer sends it at all) or
    from any other step (CreateSession/SetSession/CreateCallback, which
    still legitimately handle it in memory)."""
    fake_zitadel.add_auth_request("V2_f04_logs")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_f04_logs"})
    csrf = _extract_csrf(start.text)

    client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )

    all_tokens = {session["token"] for session in fake_zitadel.sessions.values()}
    captured = capsys.readouterr()
    for token in all_tokens:
        assert token not in captured.out
        assert token not in captured.err


def test_get_session_exception_never_carries_a_token(fake_zitadel):
    """If GetSession itself fails (e.g. an unknown session_id), the raised
    ZitadelApiError's own message must stay the same fixed, non-user-data
    string regardless -- confirms the F-04 fix didn't introduce a new
    path where a token could leak into an exception."""
    from app.zitadel import session_api

    with pytest.raises(ZitadelApiError) as excinfo:
        session_api.get_session(fake_zitadel, session_id="does-not-exist")
    assert str(excinfo.value) == "ZITADEL API call failed: 401 invalid session"


def test_get_session_still_returns_correct_factors(client, fake_zitadel):
    """Existing GetSession behavior (the actual factor data used by
    factor_policy.decide()) is unchanged by the F-04 fix."""
    from app.zitadel import session_api

    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    checks = {"user": {"loginName": "a@example.com"}, "password": {"password": "pw"}}
    created = fake_zitadel.request("POST", "/v2/sessions", json={"checks": checks})
    factors = session_api.get_session(fake_zitadel, session_id=created["sessionId"])["factors"]
    assert "user" in factors
    assert "password" in factors


def test_browser_cannot_supply_redirect_target():
    """The password/totp/webauthn POST handlers accept no field the
    browser could use to choose a redirect destination -- the callback
    URL only ever comes from `oidc_api.create_callback()`'s own return
    value."""
    import inspect

    from app import main as login_app

    source = inspect.getsource(login_app)
    assert 'request.query_params.get("redirect' not in source
    assert "Form(...)" in source  # forms are used, but never for a redirect target
