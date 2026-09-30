"""Twilio adapter configuration (docs/ROADMAP.md Phase 27.0). Mirrors
`product/ai/openai_config.py`'s own shape exactly: plain, non-secret
settings read directly from the environment, validated, cached
process-wide.

Deliberately excludes the Account SID and Auth Token -- those are secrets
(docs/ADR/0012-secrets-management.md) and are read only where actually
used, inside `product/telephony/adapters/twilio_provider.py
::TwilioTelephonyProvider.__init__()`, through
`infra.secrets.get_secrets_provider()`, never stored on this dataclass.

`TWILIO_VOICE_CALLBACK_BASE_URL` is the one piece of Twilio-adapter
configuration that is not a secret: the externally reachable base URL
Marketstack's own inbound-webhook/status-callback routes are mounted at
(`product/telephony/adapters/twilio_webhooks.py`). Twilio's REST API
requires a fully-qualified callback URL for every call/number it
provisions -- this value is what turns the relative route paths this
package defines into the absolute URLs those Twilio API calls need."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from product.telephony.errors import TelephonyProviderNotConfiguredError

MAX_BASE_URL_CHARS = 500


@dataclass(frozen=True)
class TwilioConfig:
    voice_callback_base_url: str

    def __post_init__(self) -> None:
        if not self.voice_callback_base_url.startswith(("https://", "http://")):
            raise TelephonyProviderNotConfiguredError(
                "TWILIO_VOICE_CALLBACK_BASE_URL must be an absolute http(s) URL."
            )
        if len(self.voice_callback_base_url) > MAX_BASE_URL_CHARS:
            raise TelephonyProviderNotConfiguredError(
                f"TWILIO_VOICE_CALLBACK_BASE_URL exceeds {MAX_BASE_URL_CHARS} characters."
            )


def _twilio_config_from_env() -> TwilioConfig:
    base_url = os.environ.get("TWILIO_VOICE_CALLBACK_BASE_URL")
    if not base_url:
        raise TelephonyProviderNotConfiguredError(
            "TWILIO_VOICE_CALLBACK_BASE_URL is not set -- no production Twilio provider "
            "can be built."
        )
    return TwilioConfig(voice_callback_base_url=base_url.rstrip("/"))


@lru_cache
def get_twilio_config() -> TwilioConfig:
    """Process-wide cached configuration singleton. Tests that need a
    different configuration should call `get_twilio_config.cache_clear()`
    after `monkeypatch.setenv(...)`. Raises
    `TelephonyProviderNotConfiguredError` if unset -- callers that need the
    Twilio provider to be optional catch this rather than requiring it
    eagerly, mirroring `product/ai/openai_config.py
    ::get_openai_config()`'s identical discipline."""
    return _twilio_config_from_env()


__all__ = ["MAX_BASE_URL_CHARS", "TwilioConfig", "get_twilio_config"]
