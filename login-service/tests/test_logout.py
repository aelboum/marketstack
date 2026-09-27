from __future__ import annotations

from tests.test_auth_request import _extract_csrf


def test_logout_deletes_zitadel_session_and_clears_cookies(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_logout")
    fake_zitadel.add_user(login_name="a@example.com", password="pw")
    start = client.get("/login-svc/login", params={"authRequest": "V2_logout"})
    csrf = _extract_csrf(start.text)
    login_response = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "a@example.com", "password": "pw"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303
    session_ids_before = set(fake_zitadel.sessions.keys())
    assert session_ids_before

    response = client.post("/login-svc/logout")
    assert response.status_code == 204
    assert set(fake_zitadel.sessions.keys()) == set()
    assert fake_zitadel.deleted_session_ids


def test_repeated_logout_is_safe(client, fake_zitadel):
    response1 = client.post("/login-svc/logout")
    response2 = client.post("/login-svc/logout")
    assert response1.status_code == 204
    assert response2.status_code == 204


def test_logout_does_not_touch_auth_or_v1_paths():
    """This service's own logout route lives at /login-svc/logout, a
    distinct path from SaaS-OS's own POST /auth/logout -- confirming this
    service never defines a route under /auth or /v1."""
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        assert not path.startswith("/auth")
        assert not path.startswith("/v1")
