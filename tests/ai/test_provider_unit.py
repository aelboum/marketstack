"""`FakeLLMProvider` round-trips through `LLMProvider` correctly
(docs/ROADMAP.md Phase 9), including bounded input/output. No database,
no network -- a plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.ai.errors import AIProviderError, AIValidationError
from product.ai.provider import (
    MAX_OUTPUT_CHARS,
    MAX_USER_CONTENT_CHARS,
    FakeLLMProvider,
    LLMProvider,
    clamp_output_chars,
)


def test_fake_llm_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeLLMProvider(), LLMProvider)


def test_complete_returns_deterministic_synthetic_output() -> None:
    provider = FakeLLMProvider()
    first = provider.complete(system_prompt="sys", user_content="hello", max_output_chars=100)
    second = provider.complete(system_prompt="sys", user_content="hello", max_output_chars=100)
    assert first.text == second.text
    assert first.provider_name == "fake"


def test_complete_output_differs_for_different_input() -> None:
    provider = FakeLLMProvider()
    a = provider.complete(system_prompt="sys", user_content="hello", max_output_chars=100)
    b = provider.complete(system_prompt="sys", user_content="goodbye", max_output_chars=100)
    assert a.text != b.text


def test_complete_records_every_request() -> None:
    provider = FakeLLMProvider()
    provider.complete(system_prompt="sys1", user_content="a", max_output_chars=10)
    provider.complete(system_prompt="sys2", user_content="b", max_output_chars=10)
    assert provider.requests == [("sys1", "a"), ("sys2", "b")]


def test_complete_raises_when_configured_to_fail() -> None:
    provider = FakeLLMProvider(fail=True)
    with pytest.raises(AIProviderError):
        provider.complete(system_prompt="sys", user_content="a", max_output_chars=10)


def test_complete_rejects_oversized_user_content() -> None:
    provider = FakeLLMProvider()
    with pytest.raises(AIValidationError):
        provider.complete(
            system_prompt="sys",
            user_content="x" * (MAX_USER_CONTENT_CHARS + 1),
            max_output_chars=10,
        )


def test_complete_output_never_exceeds_max_output_chars() -> None:
    provider = FakeLLMProvider()
    result = provider.complete(system_prompt="sys", user_content="a", max_output_chars=5)
    assert len(result.text) <= 5


def test_clamp_output_chars_rejects_below_one() -> None:
    assert clamp_output_chars(0) == 1
    assert clamp_output_chars(-5) == 1


def test_clamp_output_chars_caps_at_max() -> None:
    assert clamp_output_chars(MAX_OUTPUT_CHARS + 1000) == MAX_OUTPUT_CHARS
