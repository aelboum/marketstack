"""Streaming speech (STT/TTS) boundary (docs/ROADMAP.md Phase 27.0 --
"Twilio Telephony Foundation").

**Deliberately separate from `product/ai/voice_provider.py`.** That
module's existing batch `SpeechProvider` Protocol (`transcribe(bytes) ->
Transcript`, `synthesize(text) -> SynthesizedAudio`) remains completely
intact and unmodified -- a live, bidirectional telephony call needs a
fundamentally different shape (chunked audio in, interim/final transcript
events out, chunked audio out, explicit cancellation for barge-in) that
cannot be expressed by extending two whole-request methods without
breaking their existing batch contract.

**No real STT/TTS vendor is selected here** -- mirrors
`product/ai/voice_provider.py`'s own "no vendor selected" precedent
exactly. `FakeStreamingSpeechSession` is a real, deterministic, in-memory
implementation -- never a stub that "verifies nothing real," the exact
failure mode `product/telephony/provider.py`'s own module docstring warns
against.

**Pull-based audio output, for backpressure.** `pull_audio_chunk()`
returns one chunk (or `None`) per call -- the consumer (a real media
adapter's own outbound-audio loop) controls its own pace; nothing here
pushes audio faster than the consumer asks for it. `MAX_PENDING_AUDIO_CHUNKS`
bounds how much synthesized audio may queue up before `push_text_for_synthesis()`
itself starts rejecting further input -- never an unbounded queue.

**Correlation is `call_id`/`tenant_id` only, decided by the caller of this
module, never a caller-supplied token embedded in audio data itself** --
see `product/telephony/adapters/twilio_media_stream.py`'s own module
docstring for how a real adapter derives them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from product.ai.errors import AIProviderError

MAX_PENDING_AUDIO_CHUNKS = 200


@dataclass(frozen=True)
class StreamingTranscriptEvent:
    text: str
    is_final: bool


@runtime_checkable
class StreamingSpeechSession(Protocol):
    @property
    def name(self) -> str: ...

    def push_audio_chunk(self, chunk: bytes) -> list[StreamingTranscriptEvent]:
        """Feed one chunk of inbound caller audio; returns zero or more
        transcript events produced so far (`is_final=False` interim
        events may arrive before the eventual `is_final=True` one for the
        same utterance)."""
        ...

    def push_text_for_synthesis(self, text: str) -> None:
        """Queue text for outbound speech synthesis; resulting audio is
        retrieved via repeated `pull_audio_chunk()` calls."""
        ...

    def pull_audio_chunk(self) -> bytes | None:
        """Return the next queued synthesized audio chunk, or `None` if
        none is currently available -- never blocks."""
        ...

    def cancel(self) -> None:
        """Barge-in: discard any in-flight/queued synthesized audio
        immediately -- called the instant new caller speech is detected
        while TTS output is still playing."""
        ...

    def close(self) -> None:
        """Release all session state -- called on caller
        disconnect/call end. Idempotent: closing an already-closed
        session is a no-op, never an error (mirrors this repository's own
        "duplicate/late event is a no-op" discipline elsewhere, e.g.
        `product/telephony/calls.py`'s own module docstring)."""
        ...


@dataclass
class FakeStreamingSpeechSession:
    fail: bool = False
    _closed: bool = False
    _pending_audio: list[bytes] = field(default_factory=list)
    _chunk_count: int = 0

    @property
    def name(self) -> str:
        return "fake"

    def push_audio_chunk(self, chunk: bytes) -> list[StreamingTranscriptEvent]:
        if self.fail:
            raise AIProviderError("FakeStreamingSpeechSession configured to fail")
        if self._closed:
            raise AIProviderError("push_audio_chunk() called on a closed session")
        del chunk  # never invented speech content -- module docstring
        self._chunk_count += 1
        # Deterministic, visibly-synthetic (mirrors FakeSpeechProvider
        # .transcribe()'s own discipline). Every 4th chunk yields a
        # "final" event; every other chunk yields an interim one -- enough
        # for a test to exercise both branches with no real audio
        # processing.
        is_final = self._chunk_count % 4 == 0
        marker = f"[FAKE_STREAM_CHUNK count={self._chunk_count}]"
        return [StreamingTranscriptEvent(text=marker, is_final=is_final)]

    def push_text_for_synthesis(self, text: str) -> None:
        if self.fail:
            raise AIProviderError("FakeStreamingSpeechSession configured to fail")
        if self._closed:
            raise AIProviderError("push_text_for_synthesis() called on a closed session")
        if len(self._pending_audio) >= MAX_PENDING_AUDIO_CHUNKS:
            raise AIProviderError(
                f"FakeStreamingSpeechSession exceeded {MAX_PENDING_AUDIO_CHUNKS} pending "
                "audio chunks -- consumer is not pulling output."
            )
        self._pending_audio.append(f"FAKE_STREAM_AUDIO:{text}".encode())

    def pull_audio_chunk(self) -> bytes | None:
        if not self._pending_audio:
            return None
        return self._pending_audio.pop(0)

    def cancel(self) -> None:
        self._pending_audio.clear()

    def close(self) -> None:
        self._closed = True


__all__ = [
    "MAX_PENDING_AUDIO_CHUNKS",
    "FakeStreamingSpeechSession",
    "StreamingSpeechSession",
    "StreamingTranscriptEvent",
]
