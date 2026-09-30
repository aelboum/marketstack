"""Speech (STT/TTS) provider interface only -- docs/ROADMAP.md Phase 9.2,
explicitly **PARTIAL**, not complete. Mirrors `product/ai/provider.py`'s
own "no real vendor selected" precedent exactly -- `docs/INTEGRATIONS.md`
lists "AI / Voice | STT/TTS for voice agents" as its own, separate
Category D row ("kept separate from the text-LLM adapter above since
voice providers and text-model providers are typically different
vendors"), and no vendor is picked for it here either.

**What IS built here**: the `SpeechProvider` Protocol (`transcribe()`/
`synthesize()`) and `FakeSpeechProvider`, a real, deterministic, in-memory
implementation -- transcription returns a fixed, visibly-synthetic
marker string (never invented speech content), synthesis returns a fixed
byte marker (never a real audio codec payload).

**What is NOT built here**: no real STT/TTS adapter, no live wiring into
any inbound call. `product/ai/receptionist.py` is this Protocol's only
consumer, and only at the service layer -- see that module's own
docstring.

**Update (Phase 27.0)**: live audio-streaming *transport* now exists --
`product/telephony/adapters/twilio_media_stream.py` decodes/forwards a
real, live Twilio Media Stream (connected/start/media/stop events,
barge-in) -- but it is a pure transport relay with zero import coupling
to `product.ai` (structural typing only, per that module's own docstring)
and does not itself implement or call `SpeechProvider`. The STT/TTS
*vendor* decision this module's own Protocol exists to stay neutral about
remains exactly as unresolved as before -- see
`product/ai/voice_streaming.py` for the live-call-shaped Protocol variant
this transport is meant to eventually drive.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from product.ai.errors import AIProviderError


@dataclass(frozen=True)
class Transcript:
    text: str


@dataclass(frozen=True)
class SynthesizedAudio:
    audio_bytes: bytes


@runtime_checkable
class SpeechProvider(Protocol):
    @property
    def name(self) -> str: ...

    def transcribe(self, audio_bytes: bytes) -> Transcript: ...

    def synthesize(self, text: str) -> SynthesizedAudio: ...


@dataclass
class FakeSpeechProvider:
    fail: bool = False

    @property
    def name(self) -> str:
        return "fake"

    def transcribe(self, audio_bytes: bytes) -> Transcript:
        if self.fail:
            raise AIProviderError("FakeSpeechProvider configured to fail")
        digest = hashlib.sha256(audio_bytes).hexdigest()[:12]
        return Transcript(text=f"[FAKE_TRANSCRIPT digest={digest}]")

    def synthesize(self, text: str) -> SynthesizedAudio:
        if self.fail:
            raise AIProviderError("FakeSpeechProvider configured to fail")
        return SynthesizedAudio(audio_bytes=f"FAKE_AUDIO:{text}".encode())


__all__ = [
    "Transcript",
    "SynthesizedAudio",
    "SpeechProvider",
    "FakeSpeechProvider",
]
