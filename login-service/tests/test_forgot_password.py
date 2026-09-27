from __future__ import annotations

from app.ceremony import CEREMONY_COOKIE_NAME

from tests.test_auth_request import _extract_csrf


def _extract_hidden(html: str, name: str) -> str:
    marker = f'name="{name}" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _start_forgot_password(client) -> str:
    response = client.get("/login-svc/login/forgot-password")
    assert response.status_code == 200
    return _extract_csrf(response.text)


# --- GET /login-svc/login/forgot-password -----------------------------------


def test_forgot_password_form_renders_without_existing_ceremony(client, fake_zitadel):
    response = client.get("/login-svc/login/forgot-password")
    assert response.status_code == 200
    assert "Reset your password" in response.text
    assert CEREMONY_COOKIE_NAME in response.cookies


def test_login_page_links_to_forgot_password(client, fake_zitadel):
    fake_zitadel.add_auth_request("V2_link")
    response = client.get("/login-svc/login", params={"authRequest": "V2_link"})
    assert "/login-svc/login/forgot-password" in response.text


# --- POST /login-svc/login/forgot-password -- account-enumeration parity ----


def test_known_account_gets_reset_email_and_generic_response(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start_forgot_password(client)

    response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf, "login_name": "alice@example.com"},
    )

    assert response.status_code == 200
    assert "we've sent instructions" in response.text
    assert len(fake_zitadel.password_reset_url_templates) == 1


def test_unknown_account_gets_identical_generic_response_and_no_reset_call(client, fake_zitadel):
    csrf = _start_forgot_password(client)

    response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf, "login_name": "nobody@example.com"},
    )

    assert response.status_code == 200
    assert "we've sent instructions" in response.text
    assert fake_zitadel.password_reset_url_templates == []


def test_known_and_unknown_account_responses_are_byte_identical(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")

    csrf1 = _start_forgot_password(client)
    known_response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf1, "login_name": "alice@example.com"},
    )

    csrf2 = _start_forgot_password(client)
    unknown_response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf2, "login_name": "nobody@example.com"},
    )

    assert known_response.text == unknown_response.text
    assert known_response.status_code == unknown_response.status_code == 200


def test_submitted_login_name_not_leaked_in_response(client, fake_zitadel):
    csrf = _start_forgot_password(client)
    response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf, "login_name": "someone-secret@example.com"},
    )
    assert "someone-secret" not in response.text


def test_reset_url_template_points_at_reset_password_route(client, fake_zitadel):
    fake_zitadel.add_user(login_name="alice@example.com", password="s3cret!")
    csrf = _start_forgot_password(client)

    client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf, "login_name": "alice@example.com"},
    )

    [template] = fake_zitadel.password_reset_url_templates
    assert template.startswith("http://localhost:8080/login-svc/reset-password?")
    assert "{{.UserID}}" in template
    assert "{{.Code}}" in template


def test_expired_ceremony_rejects_forgot_password_submission(client, fake_zitadel):
    response = client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": "whatever", "login_name": "alice@example.com"},
    )
    assert response.status_code == 400
    assert fake_zitadel.password_reset_url_templates == []


# --- GET /login-svc/reset-password -------------------------------------------


def test_reset_password_form_renders_with_valid_looking_params(client, fake_zitadel):
    response = client.get(
        "/login-svc/reset-password", params={"userID": "123456789", "code": "AbCd1234"}
    )
    assert response.status_code == 200
    assert "Choose a new password" in response.text
    assert _extract_hidden(response.text, "user_id") == "123456789"
    assert _extract_hidden(response.text, "code") == "AbCd1234"


def test_reset_password_rejects_malformed_user_id(client, fake_zitadel):
    response = client.get(
        "/login-svc/reset-password", params={"userID": "has a space", "code": "AbCd1234"}
    )
    assert response.status_code == 400
    assert "invalid" in response.text.lower()


def test_reset_password_rejects_malformed_code(client, fake_zitadel):
    response = client.get(
        "/login-svc/reset-password", params={"userID": "123456789", "code": "has spaces"}
    )
    assert response.status_code == 400


# --- POST /login-svc/reset-password ------------------------------------------


def _request_reset(client, fake_zitadel, *, login_name="alice@example.com") -> tuple[str, str]:
    fake_zitadel.add_user(login_name=login_name, password="old-password")
    user_id = fake_zitadel.users[login_name]["user_id"]
    csrf = _start_forgot_password(client)
    client.post(
        "/login-svc/login/forgot-password",
        data={"csrf_token": csrf, "login_name": login_name},
    )
    code = fake_zitadel.password_reset_codes[user_id]
    return user_id, code


def test_successful_reset_updates_password_and_shows_done_page(client, fake_zitadel):
    user_id, code = _request_reset(client, fake_zitadel)
    get_resp = client.get("/login-svc/reset-password", params={"userID": user_id, "code": code})
    csrf = _extract_csrf(get_resp.text)

    response = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": code,
            "password": "new-password!",
            "password_confirm": "new-password!",
        },
    )

    assert response.status_code == 200
    assert "password has been updated" in response.text
    assert fake_zitadel.users["alice@example.com"]["password"] == "new-password!"


def test_mismatched_passwords_rejected_without_calling_zitadel(client, fake_zitadel):
    user_id, code = _request_reset(client, fake_zitadel)
    get_resp = client.get("/login-svc/reset-password", params={"userID": user_id, "code": code})
    csrf = _extract_csrf(get_resp.text)

    response = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": code,
            "password": "new-password!",
            "password_confirm": "different!",
        },
    )

    assert response.status_code == 200
    assert "do not match" in response.text
    # Original password untouched -- no SetPassword call was made.
    assert fake_zitadel.users["alice@example.com"]["password"] == "old-password"


def test_invalid_or_expired_code_shows_generic_error(client, fake_zitadel):
    user_id, _code = _request_reset(client, fake_zitadel)
    get_resp = client.get(
        "/login-svc/reset-password", params={"userID": user_id, "code": "WRONGCODE"}
    )
    csrf = _extract_csrf(get_resp.text)

    response = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": "WRONGCODE",
            "password": "new-password!",
            "password_confirm": "new-password!",
        },
    )

    assert response.status_code == 200
    assert "Could not reset your password" in response.text
    assert fake_zitadel.users["alice@example.com"]["password"] == "old-password"


def test_reset_ceremony_is_single_use(client, fake_zitadel):
    user_id, code = _request_reset(client, fake_zitadel)
    get_resp = client.get("/login-svc/reset-password", params={"userID": user_id, "code": code})
    csrf = _extract_csrf(get_resp.text)

    first = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": code,
            "password": "new-password!",
            "password_confirm": "new-password!",
        },
    )
    assert first.status_code == 200
    assert "password has been updated" in first.text

    # Replaying the same (now-consumed) ceremony's csrf token must fail --
    # both because the ceremony is consumed and because the code was
    # already used server-side.
    replay = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": code,
            "password": "another-password!",
            "password_confirm": "another-password!",
        },
    )
    assert replay.status_code == 400


def test_expired_ceremony_rejects_reset_submission(client, fake_zitadel):
    response = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": "whatever",
            "user_id": "123456789",
            "code": "AbCd1234",
            "password": "new-password!",
            "password_confirm": "new-password!",
        },
    )
    assert response.status_code == 400


def test_password_not_leaked_in_error_response(client, fake_zitadel):
    user_id, _code = _request_reset(client, fake_zitadel)
    get_resp = client.get(
        "/login-svc/reset-password", params={"userID": user_id, "code": "WRONGCODE"}
    )
    csrf = _extract_csrf(get_resp.text)

    response = client.post(
        "/login-svc/reset-password",
        data={
            "csrf_token": csrf,
            "user_id": user_id,
            "code": "WRONGCODE",
            "password": "super-secret-value",
            "password_confirm": "super-secret-value",
        },
    )
    assert "super-secret-value" not in response.text
