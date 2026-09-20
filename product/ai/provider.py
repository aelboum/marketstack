"""LLM provider interface only -- docs/ROADMAP.md Phase 9, explicitly
**PARTIAL**, not complete. Read this docstring before assuming a real AI
completion exists end-to-end; it does not.

**No real LLM vendor is selected**. `saas-os` `control_plane`'s own module
docstrings already establish this is not this phase's problem to solve --
`control_plane.orchestration`'s own docstring states it depends on no
"AI/LLM model or agent runtime... an open decision, not needed by this
phase," and its own test suite "invokes a plain Python stub handler
directly, exactly as a real agent runtime would call a tool, without this
module ever calling an external model itself." This module applies the
identical discipline one level down, at the one place Product code
actually needs to *call* a model: `product/ai/tools/*.py`'s own handlers.

**What IS built here**: the `LLMProvider` Protocol (mirrors
`core/email/provider.py::EmailProvider`'s exact shape -- a
`@runtime_checkable Protocol`, one `complete()` method, a normalized
result dataclass) and `FakeLLMProvider`, a real, deterministic, in-memory
implementation of it -- not a mock, a genuine implementation any test can
run against with no network access, no credentials. Its output is
deliberately, visibly synthetic (a fixed marker plus a content hash, never
prose that could be mistaken for a real model's output) -- this is what
"do not create a fake production default" concretely means: nothing here
could be mistaken for a working AI feature if it somehow reached a real
tenant.

**Bounded input/output is enforced here, not left to each tool** --
`complete()` raises `AIValidationError` for a `user_content` exceeding
`MAX_USER_CONTENT_CHARS`, and `max_output_chars` is clamped into
`[1, MAX_OUTPUT_CHARS]` before it ever reaches an implementation, so a
future real adapter inherits the same bound structurally, not by
convention.

**What is NOT built here, deliberately**: no real adapter (no vendor
selected -- `docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 does not even name
one), no `infra.secrets` credential lookup for any specific vendor, no
environment variable naming a vendor, no live registration of any tool
built against this Protocol into `control_plane.orchestration
.default_registry()` (see `product/ai/__init__.py`'s own module
docstring for why: a live-registered tool whose handler can only ever
call `FakeLLMProvider` would return synthetic output to a real tenant --
exactly the "production-looking fake success" this phase's own
instructions forbid).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from product.ai.errors import AIProviderError, AIValidationError

MAX_USER_CONTENT_CHARS = 8_000
MAX_OUTPUT_CHARS = 2_000


def clamp_output_chars(requested: int) -> int:
    if requested < 1:
        return 1
    return min(requested, MAX_OUTPUT_CHARS)


@dataclass(frozen=True)
class LLMCompletion:
    text: str
    provider_name: str


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def name(self) -> str: ...

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion: ...


@dataclass
class FakeLLMProvider:
    """An in-memory `LLMProvider` -- mirrors
    `product.telephony.provider.FakeTelephonyProvider`'s identical role.
    Records every request it was asked to complete (test assertions can
    inspect `.requests` without needing the provider to leak prompt
    content anywhere else)."""

    fail: bool = False
    requests: list[tuple[str, str]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "fake"

    def complete(
        self, *, system_prompt: str, user_content: str, max_output_chars: int
    ) -> LLMCompletion:
        if len(user_content) > MAX_USER_CONTENT_CHARS:
            raise AIValidationError(f"user_content exceeds {MAX_USER_CONTENT_CHARS} characters.")
        if self.fail:
            raise AIProviderError("FakeLLMProvider configured to fail")
        self.requests.append((system_prompt, user_content))
        bounded = clamp_output_chars(max_output_chars)
        digest = hashlib.sha256(user_content.encode("utf-8")).hexdigest()[:12]
        text = f"[FAKE_LLM_COMPLETION digest={digest}]"[:bounded]
        return LLMCompletion(text=text, provider_name=self.name)


__all__ = [
    "MAX_USER_CONTENT_CHARS",
    "MAX_OUTPUT_CHARS",
    "clamp_output_chars",
    "LLMCompletion",
    "LLMProvider",
    "FakeLLMProvider",
]
