"""`zitadel.user.v2.UserService.ListAuthenticationMethodTypes` -- verified
against `proto/zitadel/user/v2/user_service.proto` (tag v4.19.0):

    ListAuthenticationMethodTypes   GET /v2/users/{user_id}/authentication_methods

Returns which second factors (if any) a *specific* user has actually
registered (`PASSWORD`, `PASSKEY`, `IDP`, `TOTP`, `U2F`, `OTP_SMS`,
`OTP_EMAIL`, `RECOVERY_CODE`) -- `app/factor_policy.py` cross-references
this against `LoginSettings` to decide which factor (if any) to prompt
for next. Password recovery (`PasswordReset`/`UpdateUser`) is
*deliberately not implemented here* -- see `app/main.py`'s own module
docstring for why it is a documented, deferred limitation rather than an
invented flow.
"""

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
