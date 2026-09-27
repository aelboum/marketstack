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


def test_webauthn_assertion_forwarded_verbatim_to_zitadel_set_session(client, fake_zitadel):
    """F-07 behavioral strengthening, complementing the architectural
    source-inspection guard below: the exact assertion payload submitted
    to this service reaches ZITADEL's own SetSession `checks.webAuthN.
    credentialAssertionData` field completely unchanged -- proving this
    service transports the assertion rather than reconstructing or
    locally verifying it. Checked against the actual recorded fake-
    ZITADEL call, not source text."""
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    assertion = {
        "id": fake_zitadel.valid_webauthn_credential_id,
        "rawId": "cmF3",
        "type": "public-key",
        "response": {
            "authenticatorData": "YXV0aA",
            "clientDataJSON": "Y2xpZW50",
            "signature": "c2ln",
            "userHandle": None,
        },
        # A field this service has no reason to know about -- proves the
        # payload is passed through as-is, not reconstructed field-by-field.
        "clientExtensionResults": {"credProps": {"rk": True}},
    }
    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json=assertion,
    )
    assert response.status_code == 200

    set_session_calls = [
        c for c in fake_zitadel.calls if c[0] == "PATCH" and c[1].startswith("/v2/sessions/")
    ]
    webauthn_calls = [c for c in set_session_calls if c[2] and "webAuthN" in c[2].get("checks", {})]
    assert webauthn_calls, "expected a SetSession call carrying the webAuthN check"
    forwarded = webauthn_calls[-1][2]["checks"]["webAuthN"]["credentialAssertionData"]
    assert forwarded == assertion


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


# --- F-10: bounded WebAuthn request body -------------------------------------


def test_webauthn_verify_accepts_payload_comfortably_under_the_limit(client, fake_zitadel):
    """The size guard must not reject a legitimate, if unusually large,
    WebAuthn assertion -- proven with a payload far bigger than the small
    fixture used elsewhere in this file, but still well under the 16 KiB
    limit."""
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    assertion = {
        "id": fake_zitadel.valid_webauthn_credential_id,
        "rawId": "cmF3",
        "type": "public-key",
        "response": {
            "authenticatorData": "YXV0aA" * 500,  # ~3 KiB of padding, still under the limit
            "clientDataJSON": "Y2xpZW50",
            "signature": "c2ln",
            "userHandle": None,
        },
    }
    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json=assertion,
    )
    assert response.status_code == 200


def test_webauthn_verify_rejects_oversized_valid_json(client, fake_zitadel):
    """An oversized-but-otherwise-valid assertion is rejected with 413,
    regardless of whether it would have parsed successfully."""
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    assertion = {
        "id": fake_zitadel.valid_webauthn_credential_id,
        "rawId": "cmF3",
        "type": "public-key",
        "response": {
            "authenticatorData": "A" * 20_000,
            "clientDataJSON": "Y2xpZW50",
            "signature": "c2ln",
            "userHandle": None,
        },
    }
    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf},
        json=assertion,
    )
    assert response.status_code == 413
    # Never leaks internal exception details -- the fixed, generic message only.
    assert response.json() == {"error": "Request too large."}


def test_webauthn_verify_rejects_oversized_body_before_json_parsing(client, fake_zitadel):
    """The size limit is enforced before JSON parsing is even attempted --
    proven by sending a body that is BOTH oversized AND not valid JSON at
    all. If parsing had run first, malformed JSON would surface as an
    unhandled error, not this specific, fixed 413."""
    csrf = _reach_webauthn_step(client, fake_zitadel)
    client.get("/login-svc/login/webauthn/options")

    oversized_garbage = b"not-json-" + b"a" * 20_000
    response = client.post(
        "/login-svc/login/webauthn/verify",
        headers={"X-Ceremony-CSRF": csrf, "Content-Type": "application/json"},
        content=oversized_garbage,
    )
    assert response.status_code == 413
    assert response.json() == {"error": "Request too large."}
