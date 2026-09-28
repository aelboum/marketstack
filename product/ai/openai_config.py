"""OpenAI provider configuration (docs/ROADMAP.md Phase 26). Mirrors
`core/email/config.py`'s own shape exactly: plain, non-secret settings
read directly from the environment, validated, cached process-wide.

Deliberately excludes the API key -- that is a secret
(docs/ADR/0012-secrets-management.md) and is read only where it is
actually used, inside `product/ai/openai_provider.py::OpenAIProvider
.__init__()`, through `infra.secrets.get_secrets_provider()`, never
stored on this dataclass or anywhere else in this module (this mirrors
`core/email/config.py`'s own explicit "no secret persisted in a cached
configuration object a log line or exception could ever repr()/format()"
rule).

`OPENAI_MODEL` is a plain platform-level environment value, never a
tenant setting, never a workflow parameter, never a database value, and
never a hardcoded enum here -- this module does not know or care which
model names OpenAI currently offers; it only validates that a
non-empty, bounded string was configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from product.ai.errors import AIProviderNotConfiguredError

MAX_MODEL_CHARS = 200


@dataclass(frozen=True)
class OpenAIConfig:
    model: str

    def __post_init__(self) -> None:
        if not self.model or not self.model.strip():
            raise AIProviderNotConfiguredError("OPENAI_MODEL must be a non-empty string.")
        if len(self.model) > MAX_MODEL_CHARS:
            raise AIProviderNotConfiguredError(
                f"OPENAI_MODEL exceeds {MAX_MODEL_CHARS} characters."
            )


def _openai_config_from_env() -> OpenAIConfig:
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        raise AIProviderNotConfiguredError(
            "OPENAI_MODEL is not set -- no production OpenAI provider can be built. "
            "Copy .env.example to .env and set a value."
        )
    return OpenAIConfig(model=model)


@lru_cache
def get_openai_config() -> OpenAIConfig:
    """Process-wide cached configuration singleton, read once from the
    environment. Tests that need a different configuration should call
    `get_openai_config.cache_clear()` after `monkeypatch.setenv(...)`.
    Raises `AIProviderNotConfiguredError` if `OPENAI_MODEL` is unset --
    callers that need the OpenAI provider to be optional (mirrors
    `core/email/config.py::get_email_config()`'s identical "not a hard
    startup failure by itself" discipline) catch this rather than
    requiring it eagerly."""
    return _openai_config_from_env()


__all__ = ["MAX_MODEL_CHARS", "OpenAIConfig", "get_openai_config"]
