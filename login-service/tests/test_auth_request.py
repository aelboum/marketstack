from __future__ import annotations

from app.ceremony import CEREMONY_COOKIE_NAME

from tests.fakes import create_callback_calls


def test_valid_auth_request_renders_login_form(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_valid123")
    response = client.get("/login-svc/login", params={"authRequest": "V2_valid123"})
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert CEREMONY_COOKIE_NAME in response.cookies


def test_expired_or_unknown_auth_request_rejected(client, fake_zitadel):
    response = client.get("/login-svc/login", params={"authRequest": "V2_never_created"})
    assert response.status_code == 400
    assert "invalid or has expired" in response.text


def test_malformed_auth_request_id_rejected_before_any_zitadel_call(client, fake_zitadel):
    response = client.get("/login-svc/login", params={"authRequest": "not-a-valid-id"})
    assert response.status_code == 400
    assert fake_zitadel.calls == []


def test_missing_auth_request_param_rejected(client, fake_zitadel):
    response = client.get("/login-svc/login")
    assert response.status_code == 400


def test_auth_request_substitution_is_not_possible_via_form(client, fake_zitadel):
    """The auth_request_id used at CreateCallback time comes only from the
    server-side ceremony created at GET /login-svc/login -- the POST
    handler accepts no auth-request-id field from the browser at all, so
    there is no parameter to substitute."""
    fake_zitadel.add_auth_request("V2_real")
    fake_zitadel.add_user(login_name="user@example.com", password="correct horse")
    start = client.get("/login-svc/login", params={"authRequest": "V2_real"})
    csrf = _extract_csrf(start.text)

    response = client.post(
        "/login-svc/login/password",
        data={
            "csrf_token": csrf,
            "login_name": "user@example.com",
            "password": "correct horse",
            "authRequest": "V2_some_other_request",  # ignored -- no such field is read
        },
        follow_redirects=False,
    )
    assert response.status_code in (200, 303)
    calls = create_callback_calls(fake_zitadel)
    assert calls
    assert calls[0][1].endswith("/V2_real")


def _extract_csrf(html: str) -> str:
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]
