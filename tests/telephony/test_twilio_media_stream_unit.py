"""`product/telephony/adapters/twilio_media_stream.py`. No network, no
database. Part of the default `pytest` run.
"""

from __future__ import annotations

import base64
import json

import pytest
from product.telephony.adapters.twilio_media_stream import (
    MediaStreamCorrelation,
    TwilioMediaStreamHandler,
)
from product.telephony.errors import TelephonyValidationError


class _FakeSpeechSession:
    """A minimal, local stand-in satisfying `_SpeechSession`'s structural
    shape -- deliberately not `product.ai.voice_streaming
    .FakeStreamingSpeechSession`, proving the handler needs no import on
    `product.ai` at all to be fully exercised."""

    def __init__(self) -> None:
        self.pushed_chunks: list[bytes] = []
        self.closed = False
        self.cancelled = False
        self._outbound: list[bytes] = []

    def push_audio_chunk(self, chunk: bytes) -> list[object]:
        self.pushed_chunks.append(chunk)
        return []

    def queue_outbound(self, chunk: bytes) -> None:
        self._outbound.append(chunk)

    def pull_audio_chunk(self) -> bytes | None:
        if not self._outbound:
            return None
        return self._outbound.pop(0)

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> None:
        self.closed = True


def _start_message(*, tenant_id: str = "t-1", provider_call_id: str = "CA123") -> str:
    return json.dumps(
        {
            "event": "start",
            "streamSid": "MZ123",
            "start": {
                "callSid": provider_call_id,
                "customParameters": {"tenant_id": tenant_id, "provider_call_id": provider_call_id},
            },
        }
    )


def test_connected_event_is_a_no_op() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    assert handler.handle_message(json.dumps({"event": "connected"})) == []


def test_start_event_establishes_correlation_and_builds_session() -> None:
    sessions: list[_FakeSpeechSession] = []

    def factory(correlation: MediaStreamCorrelation) -> _FakeSpeechSession:
        session = _FakeSpeechSession()
        sessions.append(session)
        return session

    handler = TwilioMediaStreamHandler(factory)
    handler.handle_message(_start_message(tenant_id="tenant-42", provider_call_id="CA42"))

    assert handler.correlation == MediaStreamCorrelation(
        tenant_id="tenant-42", provider_call_id="CA42"
    )
    assert len(sessions) == 1


def test_start_event_missing_correlation_params_is_rejected() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    bad = json.dumps({"event": "start", "streamSid": "MZ1", "start": {}})
    with pytest.raises(TelephonyValidationError):
        handler.handle_message(bad)


def test_media_event_before_start_is_a_safe_no_op() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    payload = base64.b64encode(b"x").decode()
    media = json.dumps({"event": "media", "streamSid": "MZ1", "media": {"payload": payload}})
    assert handler.handle_message(media) == []


def test_media_event_decodes_and_forwards_audio() -> None:
    captured: dict[str, _FakeSpeechSession] = {}

    def factory(correlation: MediaStreamCorrelation) -> _FakeSpeechSession:
        session = _FakeSpeechSession()
        captured["session"] = session
        return session

    handler = TwilioMediaStreamHandler(factory)
    handler.handle_message(_start_message())

    payload = base64.b64encode(b"raw-audio-bytes").decode("ascii")
    handler.handle_message(
        json.dumps({"event": "media", "streamSid": "MZ123", "media": {"payload": payload}})
    )
    assert captured["session"].pushed_chunks == [b"raw-audio-bytes"]


def test_media_event_drains_outbound_audio_as_media_messages() -> None:
    def factory(correlation: MediaStreamCorrelation) -> _FakeSpeechSession:
        session = _FakeSpeechSession()
        session.queue_outbound(b"tts-chunk-1")
        session.queue_outbound(b"tts-chunk-2")
        return session

    handler = TwilioMediaStreamHandler(factory)
    handler.handle_message(_start_message())

    payload = base64.b64encode(b"caller-audio").decode("ascii")
    outbound = handler.handle_message(
        json.dumps({"event": "media", "streamSid": "MZ123", "media": {"payload": payload}})
    )
    assert len(outbound) == 2
    first = json.loads(outbound[0])
    assert first["event"] == "media"
    assert first["streamSid"] == "MZ123"
    assert base64.b64decode(first["media"]["payload"]) == b"tts-chunk-1"


def test_stop_event_closes_the_session() -> None:
    captured: dict[str, _FakeSpeechSession] = {}

    def factory(correlation: MediaStreamCorrelation) -> _FakeSpeechSession:
        session = _FakeSpeechSession()
        captured["session"] = session
        return session

    handler = TwilioMediaStreamHandler(factory)
    handler.handle_message(_start_message())
    handler.handle_message(json.dumps({"event": "stop", "streamSid": "MZ123"}))
    assert captured["session"].closed is True


def test_unrecognized_event_is_ignored() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    assert handler.handle_message(json.dumps({"event": "mark"})) == []


def test_malformed_json_is_rejected() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    with pytest.raises(TelephonyValidationError):
        handler.handle_message("{not json")


def test_barge_in_cancels_session_and_emits_clear_message() -> None:
    captured: dict[str, _FakeSpeechSession] = {}

    def factory(correlation: MediaStreamCorrelation) -> _FakeSpeechSession:
        session = _FakeSpeechSession()
        captured["session"] = session
        return session

    handler = TwilioMediaStreamHandler(factory)
    handler.handle_message(_start_message())

    clear_message = handler.barge_in()
    assert clear_message is not None
    assert captured["session"].cancelled is True
    assert json.loads(clear_message)["event"] == "clear"
    assert json.loads(clear_message)["streamSid"] == "MZ123"


def test_barge_in_before_start_is_a_safe_no_op() -> None:
    handler = TwilioMediaStreamHandler(lambda c: _FakeSpeechSession())
    assert handler.barge_in() is None
