from __future__ import annotations

from tests.fakes import create_callback_calls
from tests.test_auth_request import _extract_csrf


def _start_and_password(client, fake_zitadel, *, login_name="mfa@example.com", password="pw"):
    fake_zitadel.add_auth_request("V2_mfa")
    start = client.get("/login-svc/login", params={"authRequest": "V2_mfa"})
    csrf = _extract_csrf(start.text)
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": login_name, "password": password},
    )
    return response


def test_mfa_required_renders_totp_step_not_callback(client, fake_zitadel):
    fake_zitadel.login_settings["forceMfa"] = True
    fake_zitadel.add_user(login_name="mfa@example.com", password="pw", methods={"PASSWORD", "TOTP"})

    response = _start_and_password(client, fake_zitadel)

    assert response.status_code == 200
    assert "verification code" in response.text.lower()
    assert create_callback_calls(fake_zitadel) == []


def test_password_only_session_cannot_bypass_required_mfa_end_to_end(client, fake_zitadel):
    """The literal scenario the audit warned about: a password-only
    CreateSession must never, by itself, reach CreateCallback when the
    application/instance requires MFA."""
    fake_zitadel.login_settings["forceMfa"] = True
    fake_zitadel.add_user(login_name="mfa@example.com", password="pw", methods={"PASSWORD", "TOTP"})

    response = _start_and_password(client, fake_zitadel)

    assert response.status_code == 200  # rendered a next step, not a 303 redirect
    assert create_callback_calls(fake_zitadel) == [], "CreateCallback must not run before MFA"


def test_mfa_success_completes_login(client, fake_zitadel):
    fake_zitadel.login_settings["forceMfa"] = True
    fake_zitadel.add_user(login_name="mfa@example.com", password="pw", methods={"PASSWORD", "TOTP"})

    totp_page = _start_and_password(client, fake_zitadel)
    assert "login_svc_ceremony" in client.cookies  # ceremony persists into the MFA step
    csrf = _extract_csrf(totp_page.text)

    response = client.post(
        "/login-svc/login/totp",
        data={"csrf_token": csrf, "code": fake_zitadel.valid_totp_code},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("http://localhost:8080/auth/callback")


def test_mfa_failure_shows_generic_error_and_does_not_complete(client, fake_zitadel):
    fake_zitadel.login_settings["forceMfa"] = True
    fake_zitadel.add_user(login_name="mfa@example.com", password="pw", methods={"PASSWORD", "TOTP"})
    totp_page = _start_and_password(client, fake_zitadel)
    csrf = _extract_csrf(totp_page.text)

    response = client.post("/login-svc/login/totp", data={"csrf_token": csrf, "code": "000000"})
    assert response.status_code == 200
    assert "not correct" in response.text.lower()
    assert create_callback_calls(fake_zitadel) == []


def test_mfa_wrong_step_rejected(client, fake_zitadel):
    """A totp submission before password has ever run must not be
    accepted -- there is no pending_factor='totp' on a fresh ceremony."""
    fake_zitadel.add_auth_request("V2_mfa2")
    start = client.get("/login-svc/login", params={"authRequest": "V2_mfa2"})
    csrf = _extract_csrf(start.text)

    response = client.post("/login-svc/login/totp", data={"csrf_token": csrf, "code": "123456"})
    assert response.status_code == 400
