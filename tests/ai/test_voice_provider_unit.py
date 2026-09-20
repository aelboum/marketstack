"""`FakeSpeechProvider` round-trips through `SpeechProvider` correctly
(docs/ROADMAP.md Phase 9.2). No database, no network -- a plain unit
test, part of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.ai.errors import AIProviderError
from product.ai.voice_provider import FakeSpeechProvider, SpeechProvider


def test_fake_speech_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeSpeechProvider(), SpeechProvider)


def test_transcribe_is_deterministic() -> None:
    provider = FakeSpeechProvider()
    first = provider.transcribe(b"audio-bytes")
    second = provider.transcribe(b"audio-bytes")
    assert first.text == second.text


def test_transcribe_differs_for_different_audio() -> None:
    provider = FakeSpeechProvider()
    a = provider.transcribe(b"audio-a")
    b = provider.transcribe(b"audio-b")
    assert a.text != b.text


def test_synthesize_returns_bytes() -> None:
    provider = FakeSpeechProvider()
    result = provider.synthesize("hello")
    assert isinstance(result.audio_bytes, bytes)
    assert b"hello" in result.audio_bytes


def test_transcribe_raises_when_configured_to_fail() -> None:
    provider = FakeSpeechProvider(fail=True)
    with pytest.raises(AIProviderError):
        provider.transcribe(b"audio")


def test_synthesize_raises_when_configured_to_fail() -> None:
    provider = FakeSpeechProvider(fail=True)
    with pytest.raises(AIProviderError):
        provider.synthesize("hello")
