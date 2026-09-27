"""This service's own ZITADEL access token, obtained via the JWT Profile
/ JWT-Bearer grant (RFC 7523) against a dedicated ZITADEL machine user --
never a persistent PAT, never the bootstrap PAT, never IAM_OWNER
(docs/ADR/0017-product-owned-zitadel-login-service.md, Security
requirements):

    deploy-time generated RSA private key (mounted, this container only)
            -> signed JWT assertion (iss=sub=machine user id, aud=issuer)
            -> POST <token_endpoint>, grant_type=jwt-bearer
            -> short-lived ZITADEL access token (cached until near expiry)

The private key never leaves this process. The resulting access token is
held only in memory, never logged, never returned in any HTTP response
this service produces, never included in an exception message.

RFC 7523 SS2.1 fixes `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`
and the `assertion` form field name -- those two values are IETF-standard,
not ZITADEL-specific, and are not re-derived per deployment. The exact
required JWT claims for a ZITADEL *service user* (as opposed to an OIDC
application's own client-assertion authentication, a related but distinct
ZITADEL mechanism using a different `iss`/`sub` shape) were confirmed
against ZITADEL's own docs: `iss`/`sub` = the machine user's plain
`user_id`, `aud` = the issuer URL, `kid` header = the `key_id` returned by
`AddKey`. The token endpoint itself is never hardcoded -- it is resolved
via the same OIDC discovery document
(`<issuer>/.well-known/openid-configuration`) SaaS-OS's own
`core.identity.oidc` relies on, so a future issuer change needs no edit
here.
"""

from __future__ import annotations

import threading
import time

import httpx
import jwt

_ASSERTION_LIFETIME_SECONDS = 55 * 60  # ZITADEL requires iat not be >1h old
_TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS = 30
_SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"


class TokenAcquisitionError(RuntimeError):
    """Raised when this service cannot obtain its own ZITADEL access
    token. Never carries the private key, the signed assertion, or any
    access token -- only the HTTP status/class of the failure."""


class ZitadelCredential:
    """Caches the discovered token endpoint and the current access token.
    Thread-safe: `access_token()` is called by every inbound request
    handler."""

    def __init__(
        self,
        *,
        issuer: str,
        user_id: str,
        key_id: str,
        private_key_pem: str,
        http_client: httpx.Client,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._user_id = user_id
        self._key_id = key_id
        self._private_key_pem = private_key_pem
        self._http = http_client
        self._lock = threading.Lock()
        self._token_endpoint: str | None = None
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    def _discover_token_endpoint(self) -> str:
        if self._token_endpoint is not None:
            return self._token_endpoint
        response = self._http.get(f"{self._issuer}/.well-known/openid-configuration")
        response.raise_for_status()
        endpoint = response.json().get("token_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise TokenAcquisitionError("OIDC discovery document carried no token_endpoint.")
        self._token_endpoint = endpoint
        return endpoint

    def _mint_assertion(self) -> str:
        now = int(time.time())
        payload = {
            "iss": self._user_id,
            "sub": self._user_id,
            "aud": self._issuer,
            "iat": now,
            "exp": now + _ASSERTION_LIFETIME_SECONDS,
        }
        return jwt.encode(
            payload, self._private_key_pem, algorithm="RS256", headers={"kid": self._key_id}
        )

    def _fetch_access_token(self) -> None:
        token_endpoint = self._discover_token_endpoint()
        assertion = self._mint_assertion()
        try:
            response = self._http.post(
                token_endpoint,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                    "scope": _SCOPE,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise TokenAcquisitionError(f"transport error ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise TokenAcquisitionError(
                f"token endpoint rejected the assertion (status {response.status_code})"
            )
        try:
            body = response.json()
        except ValueError:
            raise TokenAcquisitionError("token endpoint response was not JSON") from None
        access_token = body.get("access_token")
        expires_in = body.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise TokenAcquisitionError("token endpoint response carried no access_token")
        if not isinstance(expires_in, int | float):
            expires_in = _ASSERTION_LIFETIME_SECONDS
        self._access_token = access_token
        self._access_token_expires_at = time.time() + float(expires_in)

    def access_token(self) -> str:
        with self._lock:
            expiry_cutoff = self._access_token_expires_at - _TOKEN_EXPIRY_SAFETY_MARGIN_SECONDS
            if self._access_token is None or time.time() >= expiry_cutoff:
                self._fetch_access_token()
            assert self._access_token is not None
            return self._access_token
