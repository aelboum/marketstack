"""Tests for app/config.py's Settings, focused on the F-03 security-audit
fix: production deployments must not be able to silently end up with
insecure (non-Secure) cookies.
"""

from __future__ import annotations

import pytest
from app.config import ConfigurationError, Settings

_BASE_KWARGS = dict(
    zitadel_issuer="http://zitadel.test",
    zitadel_service_user_id="user-1",
    zitadel_service_key_id="key-1",
    zitadel_service_private_key_path="/dev/null",
    public_login_service_origin="http://localhost:8080",
    brand_name="Product",
)


def test_production_with_insecure_cookies_is_rejected():
    with pytest.raises(ConfigurationError, match="LOGIN_SERVICE_COOKIE_SECURE"):
        Settings(cookie_secure=False, environment="production", **_BASE_KWARGS)


def test_production_with_secure_cookies_is_accepted():
    settings = Settings(cookie_secure=True, environment="production", **_BASE_KWARGS)
    assert settings.cookie_secure is True
    assert settings.environment == "production"


def test_development_with_insecure_cookies_remains_usable():
    """Local HTTP development must keep working -- this is the exact
    combination the local docker-compose.yml deployment uses."""
    settings = Settings(cookie_secure=False, environment="development", **_BASE_KWARGS)
    assert settings.cookie_secure is False
    assert settings.environment == "development"


def test_development_is_the_default_environment():
    settings = Settings(cookie_secure=False, **_BASE_KWARGS)
    assert settings.environment == "development"


def test_load_settings_defaults_to_secure_cookies_when_unset(monkeypatch):
    """The application's own default -- independent of any deployment
    configuration -- must be secure. This is what previously-existing
    docker-compose.yml's own `${LOGIN_SERVICE_COOKIE_SECURE:-false}`
    fallback silently defeated (security audit F-03's root cause)."""
    monkeypatch.setenv("ZITADEL_ISSUER_URL", "http://zitadel.test")
    monkeypatch.setenv("LOGIN_SERVICE_ZITADEL_USER_ID", "user-1")
    monkeypatch.setenv("LOGIN_SERVICE_ZITADEL_KEY_ID", "key-1")
    monkeypatch.setenv("LOGIN_SERVICE_PRIVATE_KEY_PATH", "/dev/null")
    monkeypatch.setenv("LOGIN_SERVICE_PUBLIC_ORIGIN", "http://localhost:8080")
    monkeypatch.delenv("LOGIN_SERVICE_COOKIE_SECURE", raising=False)
    monkeypatch.delenv("LOGIN_SERVICE_ENVIRONMENT", raising=False)

    from app.config import load_settings

    settings = load_settings()
    assert settings.cookie_secure is True
    assert settings.environment == "development"


def test_load_settings_empty_string_cookie_secure_still_defaults_to_true(monkeypatch):
    """Exact reproduction of docker-compose.yml's `${VAR:-}` shape: an
    empty string (not simply absent) must still fall through to the
    secure default, not be misread as an explicit `false`."""
    monkeypatch.setenv("ZITADEL_ISSUER_URL", "http://zitadel.test")
    monkeypatch.setenv("LOGIN_SERVICE_ZITADEL_USER_ID", "user-1")
    monkeypatch.setenv("LOGIN_SERVICE_ZITADEL_KEY_ID", "key-1")
    monkeypatch.setenv("LOGIN_SERVICE_PRIVATE_KEY_PATH", "/dev/null")
    monkeypatch.setenv("LOGIN_SERVICE_PUBLIC_ORIGIN", "http://localhost:8080")
    monkeypatch.setenv("LOGIN_SERVICE_COOKIE_SECURE", "")

    from app.config import load_settings

    assert load_settings().cookie_secure is True
