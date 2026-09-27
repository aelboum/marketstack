"""`zitadel.user.v2.UserService` -- verified against
`proto/zitadel/user/v2/user_service.proto` (tag v4.19.0):

    ListAuthenticationMethodTypes   GET  /v2/users/{user_id}/authentication_methods
    PasswordReset   POST /v2/users/{user_id}/password_reset   permission "authenticated"
    SetPassword     POST /v2/users/{user_id}/password         permission "authenticated"

`list_authentication_method_types` returns which second factors (if any) a
*specific* user has actually registered (`PASSWORD`, `PASSKEY`, `IDP`,
`TOTP`, `U2F`, `OTP_SMS`, `OTP_EMAIL`, `RECOVERY_CODE`) --
`app/factor_policy.py` cross-references this against `LoginSettings` to
decide which factor (if any) to prompt for next.

`password_reset`/`set_password` implement the forgot-password flow (this
service's own credential's `IAM_LOGIN_CLIENT` role is sufficient -- both
RPCs' own `auth_option` is just `"authenticated"`, not a fine-grained
permission, live-verified against the pinned local ZITADEL instance).
`password_reset` always requests the `sendLink` medium with this service's
own `url_template` pointing back at `/login-svc/reset-password` -- never
`returnCode` (that would hand the raw code back in this HTTP response
instead of emailing it, defeating the point of proving the requester
controls the account's mailbox)."""

from __future__ import annotations

from app.zitadel.client import ZitadelClient

_ENUM_PREFIX = "AUTHENTICATION_METHOD_TYPE_"


def list_authentication_method_types(client: ZitadelClient, *, user_id: str) -> set[str]:
    """Returns the short form of each registered method (e.g. `"TOTP"`,
    `"U2F"`), stripping ZITADEL's own enum prefix."""
    body = client.request("GET", f"/v2/users/{user_id}/authentication_methods")
    raw_types = body.get("authMethodTypes", [])
    result = set()
    for raw in raw_types:
        if isinstance(raw, str):
            result.add(raw.removeprefix(_ENUM_PREFIX))
    return result


def password_reset(client: ZitadelClient, *, user_id: str, url_template: str) -> None:
    """Sends a password-reset email to `user_id`'s registered address, with
    a link built from `url_template` (must contain the literal
    `{{.UserID}}`/`{{.Code}}` placeholders ZITADEL substitutes server-side
    -- see `proto/zitadel/user/v2/password.proto`'s own
    `SendPasswordResetLink.url_template` doc comment). Raises
    `ZitadelApiError` (e.g. `user_id` does not exist) -- callers must catch
    this and respond identically to the success case (security audit
    parity with `submit_password`'s own 401-vs-transport-error split,
    applied here to prevent account enumeration via this endpoint)."""
    client.request(
        "POST",
        f"/v2/users/{user_id}/password_reset",
        json={
            "sendLink": {
                "notificationType": "NOTIFICATION_TYPE_Email",
                "urlTemplate": url_template,
            }
        },
    )


def set_password(
    client: ZitadelClient, *, user_id: str, password: str, verification_code: str
) -> None:
    """Completes a password reset using the code from `password_reset`'s
    emailed link. Raises `ZitadelApiError` for an invalid/expired code or a
    password-policy rejection alike -- the caller intentionally does not
    distinguish the two in what it shows the user (both map to one generic,
    actionable message; see `app/main.py`'s `submit_reset_password`)."""
    client.request(
        "POST",
        f"/v2/users/{user_id}/password",
        json={
            "newPassword": {"password": password, "changeRequired": False},
            "verificationCode": verification_code,
        },
    )
