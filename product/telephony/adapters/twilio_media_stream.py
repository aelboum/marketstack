"""Twilio Media Streams adapter (docs/ROADMAP.md Phase 27.0 -- "Twilio
Telephony Foundation").

Owns everything Twilio-specific about live call audio: the WebSocket
message JSON shape (`connected`/`start`/`media`/`stop`), Twilio's own
base64 audio framing, and the `streamSid` identifier -- none of that
crosses outside this module.

**No import on `product.ai`, deliberately** -- mirrors
`product/telephony/call_session.py`'s own module docstring exactly:
"`product.telephony` is not permitted to depend on `product.ai`; the
reverse edge is the one this repository's own import-linter contract
allows." `_SpeechSession` below is a small, structurally-typed `Protocol`
declared *in this module*, matching the shape of
`product/ai/voice_streaming.py::StreamingSpeechSession` closely enough
that any real implementation of that Protocol already satisfies this one
too, with zero import coupling -- Python's structural typing does the
work a cross-module import would otherwise require. Whatever composition
layer eventually wires a real speech session into this adapter (a future
phase's own analogue of `product/call_action_safety.py`) is what actually
imports both sides; this module never does.

**Correlation via TwiML `<Parameter>`, never caller-controlled data.**
When the inbound-call webhook
(`product/telephony/adapters/twilio_webhooks.py`) starts a Media Stream,
it is expected to set `tenant_id`/`provider_call_id` as `<Parameter>`
elements on the `<Start><Stream>` TwiML verb -- Twilio echoes these back
verbatim in the `start` event's own `customParameters` field. This is
server-set correlation data, not caller-supplied: the caller's own
audio/speech has no way to influence it, mirroring
`product/telephony/adapters/twilio_webhooks.py`'s own transfer-event-URL
reasoning for the identical "Twilio relays exactly what we told it, an
attacker cannot inject a different value here" property.

**Synchronous, testable core; the async WebSocket loop lives at a future
call site.** `TwilioMediaStreamHandler.handle_message()` takes one raw
Twilio JSON text frame and returns zero or more outbound JSON text frames
to send back -- no `asyncio`, no live socket, anywhere in this class. No
route wires this to a real ASGI WebSocket in this pass (docs/ROADMAP.md
Phase 27.0's own "do not implement Phase 26" instruction -- there is no
real `StreamingSpeechSession` implementation yet for such a route to be
meaningfully exercised against)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from product.telephony.errors import TelephonyValidationError

_EVENT_CONNECTED = "connected"
_EVENT_START = "start"
_EVENT_MEDIA = "media"
_EVENT_STOP = "stop"


@runtime_checkable
class _SpeechSession(Protocol):
    """Structurally matches `product/ai/voice_streaming.py
    ::StreamingSpeechSession` -- see module docstring for why this is a
    local, re-declared shape rather than an import."""

    def push_audio_chunk(self, chunk: bytes) -> list[object]: ...
    def pull_audio_chunk(self) -> bytes | None: ...
    def cancel(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MediaStreamCorrelation:
    tenant_id: str
    provider_call_id: str


class TwilioMediaStreamHandler:
    """One instance per live Media Streams WebSocket connection.
    `speech_session_factory` is called exactly once, from the `start`
    event, with the correlation Twilio just echoed back -- never before,
    since the correlation is not known until then."""

    def __init__(
        self, speech_session_factory: Callable[[MediaStreamCorrelation], _SpeechSession]
    ) -> None:
        self._speech_session_factory = speech_session_factory
        self._session: _SpeechSession | None = None
        self._stream_sid: str | None = None
        self._correlation: MediaStreamCorrelation | None = None

    @property
    def correlation(self) -> MediaStreamCorrelation | None:
        return self._correlation

    def handle_message(self, raw_text: str) -> list[str]:
        try:
            message = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise TelephonyValidationError("malformed Twilio Media Streams message.") from exc
        if not isinstance(message, dict):
            raise TelephonyValidationError("Twilio Media Streams message was not an object.")

        event = message.get("event")
        if event == _EVENT_CONNECTED:
            return []
        if event == _EVENT_START:
            return self._handle_start(message)
        if event == _EVENT_MEDIA:
            return self._handle_media(message)
        if event == _EVENT_STOP:
            return self._handle_stop()
        # An unrecognized event (a future Twilio addition, or a `mark`
        # playback acknowledgment) -- ignored, never an error.
        return []

    def _handle_start(self, message: dict) -> list[str]:
        start = message.get("start")
        if not isinstance(start, dict):
            raise TelephonyValidationError("Twilio 'start' message missing its own 'start' object.")
        stream_sid = message.get("streamSid")
        if not isinstance(stream_sid, str) or not stream_sid:
            raise TelephonyValidationError("Twilio 'start' message missing 'streamSid'.")
        params = start.get("customParameters")
        if not isinstance(params, dict):
            params = {}
        tenant_id = params.get("tenant_id")
        provider_call_id = params.get("provider_call_id")
        if not isinstance(tenant_id, str) or not isinstance(provider_call_id, str):
            raise TelephonyValidationError(
                "Twilio Media Stream 'start' event is missing required correlation "
                "customParameters (tenant_id/provider_call_id)."
            )
        self._stream_sid = stream_sid
        self._correlation = MediaStreamCorrelation(
            tenant_id=tenant_id, provider_call_id=provider_call_id
        )
        self._session = self._speech_session_factory(self._correlation)
        return []

    def _handle_media(self, message: dict) -> list[str]:
        if self._session is None:
            # A media frame before 'start' -- Twilio's own documented
            # ordering never does this; a no-op, never a crash.
            return []
        media = message.get("media")
        if not isinstance(media, dict):
            return []
        payload = media.get("payload")
        if not isinstance(payload, str):
            return []
        try:
            chunk = base64.b64decode(payload)
        except (ValueError, TypeError):
            return []
        self._session.push_audio_chunk(chunk)
        return self._drain_outbound_audio()

    def _handle_stop(self) -> list[str]:
        if self._session is not None:
            self._session.close()
        self._session = None
        return []

    def _drain_outbound_audio(self) -> list[str]:
        if self._session is None or self._stream_sid is None:
            return []
        outbound: list[str] = []
        while True:
            chunk = self._session.pull_audio_chunk()
            if chunk is None:
                break
            outbound.append(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": self._stream_sid,
                        "media": {"payload": base64.b64encode(chunk).decode("ascii")},
                    }
                )
            )
        return outbound

    def barge_in(self) -> str | None:
        """Called the instant new caller speech is detected while TTS
        output may still be playing -- cancels the speech session's own
        queued audio and tells Twilio to clear whatever it has already
        buffered for playback (Twilio's own documented `clear` message)."""
        if self._session is None or self._stream_sid is None:
            return None
        self._session.cancel()
        return json.dumps({"event": "clear", "streamSid": self._stream_sid})


__all__ = ["MediaStreamCorrelation", "TwilioMediaStreamHandler"]
