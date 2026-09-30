"""`product/ai/voice_streaming.py`. No network, no database. Part of the
default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.ai.errors import AIProviderError
from product.ai.voice_streaming import (
    MAX_PENDING_AUDIO_CHUNKS,
    FakeStreamingSpeechSession,
    StreamingSpeechSession,
    StreamingTranscriptEvent,
)


def test_implements_streaming_speech_session_protocol() -> None:
    assert isinstance(FakeStreamingSpeechSession(), StreamingSpeechSession)


def test_name_is_fake() -> None:
    assert FakeStreamingSpeechSession().name == "fake"


def test_push_audio_chunk_yields_interim_then_final() -> None:
    session = FakeStreamingSpeechSession()
    events: list[StreamingTranscriptEvent] = []
    for _ in range(4):
        events.extend(session.push_audio_chunk(b"\x00\x01"))
    assert [e.is_final for e in events] == [False, False, False, True]


def test_push_audio_chunk_never_echoes_raw_audio_as_text() -> None:
    session = FakeStreamingSpeechSession()
    events = session.push_audio_chunk(b"not-real-audio-bytes")
    assert all("not-real-audio-bytes" not in e.text for e in events)


def test_synthesis_round_trip() -> None:
    session = FakeStreamingSpeechSession()
    session.push_text_for_synthesis("hello")
    chunk = session.pull_audio_chunk()
    assert chunk == b"FAKE_STREAM_AUDIO:hello"
    assert session.pull_audio_chunk() is None


def test_cancel_discards_queued_audio() -> None:
    session = FakeStreamingSpeechSession()
    session.push_text_for_synthesis("hello")
    session.cancel()
    assert session.pull_audio_chunk() is None


def test_close_is_idempotent_and_rejects_further_input() -> None:
    session = FakeStreamingSpeechSession()
    session.close()
    session.close()  # idempotent -- never an error
    with pytest.raises(AIProviderError):
        session.push_audio_chunk(b"\x00")
    with pytest.raises(AIProviderError):
        session.push_text_for_synthesis("hello")


def test_configured_to_fail_raises() -> None:
    session = FakeStreamingSpeechSession(fail=True)
    with pytest.raises(AIProviderError):
        session.push_audio_chunk(b"\x00")
    with pytest.raises(AIProviderError):
        session.push_text_for_synthesis("hello")


def test_pending_audio_bound_is_enforced() -> None:
    session = FakeStreamingSpeechSession()
    for _ in range(MAX_PENDING_AUDIO_CHUNKS):
        session.push_text_for_synthesis("x")
    with pytest.raises(AIProviderError):
        session.push_text_for_synthesis("one-too-many")
