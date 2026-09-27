"""`zitadel.settings.v2.SettingsService.GetLoginSettings` -- verified
against `proto/zitadel/settings/v2/login_settings.proto` (tag v4.19.0):

    GetLoginSettings   GET  /v2/settings/login   permission policy.read

Relevant fields on the returned `LoginSettings`: `forceMfa`,
`forceMfaLocalOnly` (force_mfa takes precedence when both are set),
`secondFactors` (allow-listed second-factor types), `multiFactors`.
`app/factor_policy.py` is the only module that interprets these values.
"""

from __future__ import annotations

from app.zitadel.client import ZitadelClient


def get_login_settings(client: ZitadelClient) -> dict:
    body = client.request("GET", "/v2/settings/login")
    return body.get("settings", body)
