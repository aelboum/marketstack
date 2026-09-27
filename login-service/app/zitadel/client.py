"""Low-level authenticated ZITADEL API request helper, shared by every
`zitadel/*_api.py` module. All REST paths/permissions used across this
package were verified against the actual v4.19.0 proto sources (not
invented) -- see each `*_api.py` module's own docstring for the specific
RPC it wraps.
"""

from __future__ import annotations

import httpx

from app.zitadel.token import ZitadelCredential


class ZitadelApiError(RuntimeError):
    """Raised for any non-2xx ZITADEL API response. Carries only the HTTP
    status and a short, non-user-data classification -- never the
    request/response body verbatim (which may carry a login name or other
    end-user data that must not end up in a generic exception surfaced
    higher up)."""

    def __init__(self, status_code: int, reason: str) -> None:
        super().__init__(f"ZITADEL API call failed: {status_code} {reason}")
        self.status_code = status_code
        self.reason = reason


class ZitadelClient:
    def __init__(self, *, base_url: str, credential: ZitadelCredential, http_client: httpx.Client):
        self._base_url = base_url.rstrip("/")
        self._credential = credential
        self._http = http_client

    def request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        token = self._credential.access_token()
        try:
            response = self._http.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise ZitadelApiError(0, f"transport error ({type(exc).__name__})") from None
        if response.status_code >= 300:
            raise ZitadelApiError(response.status_code, "request rejected")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            raise ZitadelApiError(response.status_code, "response was not JSON") from None
