"""AI receptionist advisory decision + tool (docs/ROADMAP.md Phase 9.2).

**Scope, deliberately narrow** -- Phase 9.2's own Objective is "an AI
agent handling inbound calls... using registered tools for call context,
with human handoff (Phase 8.4) as the defined escalation path." Building
a real-time voice agent needs three things this codebase does not have
and this pass does not invent: a selected STT/TTS vendor
(`product/ai/voice_provider.py`'s own module docstring), a selected LLM
vendor (`product/ai/provider.py`'s own), and a live audio/media stream
into an inbound call (`product/telephony/`'s own tables track call
*metadata* only -- Phase 8 never built call-audio streaming, and its own
inbound webhook receiver is itself not live, see
`product/telephony/__init__.py`). What this module builds instead is the
one piece that is real, bounded, and fully testable without any of that:
**the advisory decision** a real voice-agent runtime would consult on
every turn -- given a transcript and a confidence score, should the AI
attempt to handle this turn itself, or should the call escalate to the
human it is already routed to?

**"Human handoff" here means: consult Phase 8's own existing routing
decision, never invent a second one.** `product/telephony/routing.py
::route_inbound_call()` already assigns an inbound call to a human agent
synchronously, at `call.initiated` time (`product/telephony/calls.py`).
This module never transitions a `Call`'s status, never reassigns it,
never builds a new handoff/notification mechanism (that remains Phase
8.4's own, still-deferred scope, unchanged by this phase) -- `escalate`
here means "the AI declines to draft a response for this turn; whichever
human `Call.assigned_user_id` already names remains the one handling it,"
which `build_receptionist_advice_tool()`'s own handler surfaces in its
output for a caller to act on, never acts on itself
(docs/ROADMAP.md Phase 9's own "the model may request an action; Product/
SaaS-OS authorization must independently decide" requirement -- this
tool's output is advice, not an executed action).

**No live wiring** -- like every other tool in `product/ai/tools/`, this
is never registered into `control_plane.orchestration.default_registry()`
(`product/ai/__init__.py`'s own module docstring). Phase 8's own inbound
webhook receiver has no live HTTP route to call this from even if it
were.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.errors import AIValidationError
from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.validation import MAX_STRING_FIELD_CHARS, require_bounded_string, require_uuid
from product.telephony.calls import get_call
from product.telephony.models import STATUS_IN_PROGRESS, STATUS_RINGING
from product.telephony.permissions import CALL_RESOURCE

TOOL_KEY = "ai.telephony.receptionist_advice"

# A disclosed, provisional boundary -- not evidence-based (no real calls
# have ever been handled by this system), per this phase's own "escalates
# outside a defined confidence/scope boundary" requirement: the boundary
# must be *defined*, not that this specific value is validated. A future
# phase revisiting this with real call data may move it.
ESCALATION_CONFIDENCE_THRESHOLD = 0.6

ReceptionistAction = Literal["handle", "escalate"]

_SYSTEM_PROMPT = (
    "You are an AI phone receptionist. Given a caller's transcript, draft "
    "a brief spoken response. Never invent facts not present in the "
    "input. If you are unsure, say so plainly rather than guessing."
)

_HANDLEABLE_CALL_STATUSES = frozenset({STATUS_RINGING, STATUS_IN_PROGRESS})


def decide_receptionist_action(confidence: float) -> ReceptionistAction:
    """Pure decision function -- no I/O, no provider call. `confidence`
    must be in `[0, 1]`; anything else is a caller bug, not a confidence
    score, and is rejected rather than silently clamped (clamping an
    out-of-range confidence into range would hide the exact kind of bug
    this boundary exists to catch)."""
    if not (0.0 <= confidence <= 1.0):
        raise AIValidationError(f"confidence must be in [0, 1], got {confidence!r}.")
    return "handle" if confidence >= ESCALATION_CONFIDENCE_THRESHOLD else "escalate"


def build_receptionist_advice_tool(provider: LLMProvider) -> ToolDefinition:
    async def _handler(
        context: ToolExecutionContext, payload: Mapping[str, object]
    ) -> dict[str, object]:
        call_id = require_uuid(payload, "call_id")
        transcript = require_bounded_string(payload, "transcript")
        confidence_raw = payload.get("confidence")
        if not isinstance(confidence_raw, (int, float)) or isinstance(confidence_raw, bool):
            raise AIValidationError("payload.confidence must be a number.")
        confidence = float(confidence_raw)

        call = get_call(context.agent_user_id, context.tenant_id, call_id)
        if call.status not in _HANDLEABLE_CALL_STATUSES:
            raise AIValidationError(
                f"call {call_id} is not in a handleable state (status={call.status!r})."
            )

        action = decide_receptionist_action(confidence)
        draft_response: str | None = None
        if action == "handle":
            completion = provider.complete(
                system_prompt=_SYSTEM_PROMPT,
                user_content=transcript,
                max_output_chars=MAX_OUTPUT_CHARS,
            )
            draft_response = completion.text

        return {
            "call_id": str(call.id),
            "action": action,
            "confidence": confidence,
            "draft_response": draft_response,
            "assigned_user_id": (
                str(call.assigned_user_id) if call.assigned_user_id is not None else None
            ),
        }

    return ToolDefinition(
        key=TOOL_KEY,
        description=(
            "Advise whether the AI receptionist should attempt to handle the current "
            "call turn or defer to the already-routed human -- advisory only, never "
            "executes a state change."
        ),
        handler=_handler,
        required_scope_type="tenant",
        required_resource=CALL_RESOURCE,
        required_action="read",
        autonomy_tier=0,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=True,
    )


__all__ = [
    "ESCALATION_CONFIDENCE_THRESHOLD",
    "MAX_STRING_FIELD_CHARS",
    "ReceptionistAction",
    "TOOL_KEY",
    "build_receptionist_advice_tool",
    "decide_receptionist_action",
]
