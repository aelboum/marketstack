from __future__ import annotations

from tests.fakes import create_callback_calls
from tests.test_auth_request import _extract_csrf


def _reach_webauthn_step(client, fake_zitadel):
    fake_zitadel.login_settings["forceMfa"] = True
    fake_zitadel.add_user(login_name="wa@example.com", password="pw", methods={"PASSWORD", "U2F"})
    fake_zitadel.add_auth_request("V2_wa")
    start = client.get("/login-svc/login", params={"authRequest": "V2_wa"})
    csrf = _extract_csrf(start.text)
    page = client.post(
        "/login-svc/login/password",
        data={"csrf_token": csrf, "login_name": "wa@example.com", "password": "pw"},
    )
    assert "security key" in page.text.lower()
    return csrf


def test_webauthn_options_endpoint_returns_challenge(client, fake_zitadel):
    _reach_webauthn_step(client, fake_zitadel)
    response = client.get("/login-svc/login/webauthn/options")
    assert response.status_code == 200
    body = response.json()
    assert "publicKey" in body
    assert body["publicKey"]["challenge"]


def test_successful_assertion_completes_login(client, fake_zitadel):
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")  # requests the challenge, like the page's JS

    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json={
            "id": fake_zitadel.valid_webauthn_credential_id,
            "rawId": "cmF3",
            "type": "public-key",
            "response": {
                "authenticatorData": "YXV0aA",
                "clientDataJSON": "Y2xpZW50",
                "signature": "c2ln",
                "userHandle": None,
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["redirect"].startswith("http://localhost:8080/auth/callback")


def test_failed_assertion_does_not_complete_login(client, fake_zitadel):
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json={
            "id": "wrong-credential-id",
            "rawId": "cmF3",
            "type": "public-key",
            "response": {
                "authenticatorData": "YXV0aA",
                "clientDataJSON": "Y2xpZW50",
                "signature": "YmFk",
                "userHandle": None,
            },
        },
    )
    assert response.status_code == 400
    assert create_callback_calls(fake_zitadel) == []


def test_malformed_assertion_rejected_not_crashed(client, fake_zitadel):
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json={"garbage": True},
    )
    assert response.status_code == 400


def test_no_local_webauthn_verification_only_zitadel_session_api_used(client, fake_zitadel):
    """The assertion is forwarded verbatim to the fake ZITADEL's
    SetSession -- this service never inspects/verifies signature bytes
    itself (no cryptography import anywhere in app/zitadel/session_api.py
    or app/main.py's webauthn routes)."""
    import inspect

    from app import main as login_app
    from app.zitadel import session_api

    source = inspect.getsource(session_api) + inspect.getsource(login_app)
    for forbidden in ("cryptography", "verify_signature", "cbor", "fido2"):
        assert forbidden not in source.lower()
