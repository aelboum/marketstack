from __future__ import annotations

import httpx
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


# --- F-12: service/transport failures no longer present as bad credentials ---


class _StubCredential:
    """Satisfies `ZitadelClient`'s duck-typed `credential` argument without
    exercising the real JWT-bearer token flow -- irrelevant to what these
    tests prove (CreateSession's own failure classification)."""

    def access_token(self) -> str:
        return "test-access-token"


def _real_zitadel_client_with_transport(handler):
    """A real `ZitadelClient` (not `FakeZitadel`) wired to an
    `httpx.MockTransport` -- drives the actual sanitizing HTTP client path
    (`app/zitadel/client.py::ZitadelClient.request()`), the same technique
    already established for F-08 in `test_security.py`."""
    from app.zitadel.client import ZitadelClient

    return ZitadelClient(
        base_url="http://zitadel.test",
        credential=_StubCredential(),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_zitadel_service_failure_shows_temporary_service_message_not_bad_credentials(
    client, fake_zitadel, monkeypatch
):
    """A ZITADEL 5xx (service failure, not an authentication rejection)
    must not be presented as "Invalid email or password." -- and must not
    leak the status code, reason, URL, or any other exception detail."""
    from app import main as login_app

    # Reach the password form normally (via the still-working fake) so a
    # real, cookie-carried ceremony exists -- only CreateSession itself
    # fails below.
    csrf = _start(client, fake_zitadel, auth_request_id="V2_svcfail")

    marker = "SENSITIVE-DETAIL-b7e2f9"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"upstream failure: {marker}")

    monkeypatch.setattr(login_app, "zitadel", _real_zitadel_client_with_transport(handler))

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
    )

    assert response.status_code == 200
    assert "Authentication service temporarily unavailable. Please try again." in response.text
    assert "Invalid email or password." not in response.text
    assert marker not in response.text
    assert "503" not in response.text
    assert "zitadel.test" not in response.text


def test_zitadel_transport_failure_shows_temporary_service_message(
    client, fake_zitadel, monkeypatch
):
    """A transport-level failure (`ZitadelApiError(0, ...)`, per
    `app/zitadel/client.py`'s own `except httpx.HTTPError` branch) is also
    a service failure, not an authentication rejection."""
    from app import main as login_app

    csrf = _start(client, fake_zitadel, auth_request_id="V2_transportfail")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(login_app, "zitadel", _real_zitadel_client_with_transport(handler))

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
    )

    assert response.status_code == 200
    assert "Authentication service temporarily unavailable. Please try again." in response.text
    assert "Invalid email or password." not in response.text
    assert "ConnectError" not in response.text
    assert "connection refused" not in response.text


def test_zitadel_service_failure_remains_fail_closed(client, fake_zitadel, monkeypatch):
    """A service failure during CreateSession never produces a session,
    callback, authenticated-session cookie, or redirect -- exactly like
    the existing invalid-credentials path, just with a different message."""
    from app import main as login_app

    csrf = _start(client, fake_zitadel, auth_request_id="V2_failclosed")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    monkeypatch.setattr(login_app, "zitadel", _real_zitadel_client_with_transport(handler))

    response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "alice@example.com", "password": "s3cret!"},
        follow_redirects=False,
    )

    assert response.status_code == 200  # never the 303 a successful login produces
    assert create_callback_calls(fake_zitadel) == []
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert not any("login_svc_zitadel_session" in h for h in set_cookie_headers)
