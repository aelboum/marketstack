"""Login Service runtime configuration (docs/ADR/0017). Read directly from
the environment, mirroring this repository's existing convention
(`product`'s own `api/auth/config.py` equivalent inside saas-os) -- this
service never imports that code, it only mirrors the *pattern*.

Every value here is non-secret. The one secret this service needs (the
RSA private key) is read from a file path, never from an environment
variable value -- see `zitadel/token.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(ValueError):
    """Raised for a missing/invalid setting. Never includes a secret --
    nothing here is one."""


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigurationError(f"{name} must be set.")
    return value


def _optional(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # ZITADEL: same instance the product backend's own OIDC flow talks to.
    zitadel_issuer: str
    # This service's own ZITADEL machine-user identity (IAM_LOGIN_CLIENT
    # role -- the only built-in ZITADEL role that carries `session.link`,
    # verified against cmd/defaults.yaml at the pinned ZITADEL version;
    # see scripts/provision_login_service_credential.py's own docstring).
    # Never `project.app.write` -- that stays with the separate
    # application-configuration credential
    # (scripts/configure_zitadel_login_v2.py), never this service's.
    zitadel_service_user_id: str
    zitadel_service_key_id: str
    zitadel_service_private_key_path: str

    # This service's own public origin, as the browser reaches it through
    # Caddy (e.g. http://localhost:8080/login-svc locally) -- used only for
    # the WebAuthn RP "domain" passed to ZITADEL's Session API, never for
    # building a redirect target (redirects only ever come from ZITADEL's
    # own CreateCallback response -- see app/main.py).
    public_login_service_origin: str

    cookie_secure: bool
    brand_name: str
    # Mirrors SaaS-OS's own `ENVIRONMENT` posture (`api/auth/config.py`'s
    # `AuthHttpConfig`/`AUTH_COOKIE_SECURE`): "development" is the only
    # value that may pair with `cookie_secure=False` -- see
    # `__post_init__` below (security audit F-03). Never read by any
    # other part of this service; this is its one purpose.
    environment: str = "development"

    def __post_init__(self) -> None:
        # Repeated here (not just in load_settings()) so a directly
        # constructed Settings object can't bypass it either -- same
        # reasoning as AuthHttpConfig.__post_init__'s own docstring.
        if self.environment == "production" and not self.cookie_secure:
            raise ConfigurationError(
                "LOGIN_SERVICE_COOKIE_SECURE cannot be disabled when "
                "LOGIN_SERVICE_ENVIRONMENT=production."
            )


def load_settings() -> Settings:
    return Settings(
        zitadel_issuer=_require("ZITADEL_ISSUER_URL"),
        zitadel_service_user_id=_require("LOGIN_SERVICE_ZITADEL_USER_ID"),
        zitadel_service_key_id=_require("LOGIN_SERVICE_ZITADEL_KEY_ID"),
        zitadel_service_private_key_path=_require("LOGIN_SERVICE_PRIVATE_KEY_PATH"),
        public_login_service_origin=_require("LOGIN_SERVICE_PUBLIC_ORIGIN"),
        cookie_secure=_bool("LOGIN_SERVICE_COOKIE_SECURE", True),
        brand_name=_optional("LOGIN_SERVICE_BRAND_NAME", "Product"),
        environment=_optional("LOGIN_SERVICE_ENVIRONMENT", "development"),
    )
