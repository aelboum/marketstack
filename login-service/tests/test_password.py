from __future__ import annotations

from app.ceremony import CEREMONY_COOKIE_NAME

from tests.fakes import create_callback_calls
from tests.test_auth_request import _extract_csrf


def _start(client, fake_zitadel, auth_request_id="V2_pw"):
    fake_zitadel.add_auth_request(auth_request_id)
    response = client.get("/login-svc/login", params={"authRequest": auth_request_id})
    return _extract_csrf(response.text)


def test_password_success_no_mfa_redirects_to_callback(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start(client, fake_zitadel)

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("http://localhost:8080/auth/callback")


def test_password_failure_shows_generic_invalid_credentials_message(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start(client, fake_zitadel)

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "wrong"},
    )
    assert response.status_code == 200
    assert "Invalid email or password." in response.text
    # No leakage of which check failed, or the submitted credential value.
    assert "wrong" not in response.text


def test_unknown_account_gets_identical_generic_message(client, fake_zitadel):
    csrf = _start(client, fake_zitadel)
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "nobody@example.com", "password": "whatever"},
    )
    assert response.status_code == 200
    assert "Invalid email or password." in response.text


def test_locked_or_invalid_account_does_not_create_callback(client, fake_zitadel):
    csrf = _start(client, fake_zitadel)
    client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "nobody@example.com", "password": "whatever"},
    )
    assert create_callback_calls(fake_zitadel) == []


def test_no_credential_leakage_in_response_headers_or_cookies(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start(client, fake_zitadel)
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
        follow_redirects=False,
    )
    for cookie in response.cookies:
        assert "s3cret" not in str(response.cookies.get(cookie))
    assert "s3cret" not in str(response.headers)


def test_successful_password_login_sets_zitadel_session_cookie_scoped_narrow(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start(client, fake_zitadel)
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
        follow_redirects=False,
    )
    set_cookie_headers = response.headers.get_list("set-cookie")
    zitadel_session_headers = [h for h in set_cookie_headers if "login_svc_zitadel_session" in h]
    assert zitadel_session_headers
    assert "Path=/login-svc" in zitadel_session_headers[0]
    assert "HttpOnly" in zitadel_session_headers[0]


def test_expired_ceremony_rejects_password_submission(client, fake_zitadel):
    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": "whatever", "login_name": "alice@example.com", "password": "x"},
    )
    assert response.status_code == 400
    assert CEREMONY_COOKIE_NAME not in response.cookies
