"""`ai.crm.qualify_lead` tool (docs/ROADMAP.md Phase 9.1, structured
decision added Phase 26A).

Reads one `crm.contacts` row (`product.crm.contacts.get_contact()`, the
same read `docs/ADR/0006-ai-depends-on-crm-conversations-telephony.md`
sanctions) and asks the injected `LLMProvider` for a structured
qualification result. Tier 0 (direct-invocation), read-only side effect,
`tenant_data` classification, Data-Authorization-gated -- see
`product/ai/provider.py`'s own module docstring for why a
`FakeLLMProvider`-backed call can never produce a real `decision` (its
output is a deterministic, visibly-synthetic marker, not JSON -- only a
real provider, or a test double built for this tool's own contract, can).

**`required_resource`/`required_action` reuse `crm.contact`/`read`
verbatim** -- an invoking agent that cannot already read this contact via
ordinary CRM access cannot qualify it via this tool either (ADR-0006's
own "defense in depth, not a new authorization path" point).

**Structured decision, parsed here, not in the provider.** The model is
asked for one JSON object (`decision`, `reason`, `qualification`) in the
same single `LLMProvider.complete()` call this tool always made -- no
second call, no change to `LLMProvider`/`LLMCompletion`
(`product/ai/provider.py`) or to `product/ai/openai_provider.py`, which
both remain ignorant of this tool's own response shape, exactly as
`product/ai/receptionist.py`'s own `ReceptionistAction` Literal is local
to that tool. `decision` is a closed, three-value vocabulary; a model
response that is not valid JSON, is missing a required field, has a
wrong-typed or out-of-vocabulary `decision`, or exceeds the bounds below
is rejected with `AIProviderError` -- the same error
`product/ai/openai_provider.py` already raises for "OpenAI returned an
empty or malformed response," never silently coerced or truncated into a
best-effort guess (docs/ROADMAP.md Phase 26's own "no silent fallback to
an invented decision" requirement).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, cast

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.errors import AIProviderError
from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.validation import require_uuid
from product.crm.contacts import get_contact
from product.crm.permissions import CONTACT_RESOURCE

TOOL_KEY = "ai.crm.qualify_lead"

#: A closed, three-value vocabulary -- mirrors
#: `product/ai/receptionist.py::ReceptionistAction`'s identical
#: tool-local `Literal` convention. Never `confidence`/`risk`/`score`/
#: `probability`/`recommended_action`/`autonomy_tier` -- those are
#: explicitly out of scope for this phase.
QualifyLeadDecision = Literal["qualified", "not_qualified", "needs_more_info"]

_VALID_DECISIONS: frozenset[str] = frozenset(
    {"qualified", "not_qualified", "needs_more_info"}
)

#: `reason` is a short explanation, deliberately bounded well under the
#: existing `MAX_OUTPUT_CHARS` (2000) the free-form `qualification` note
#: already uses -- a one-sentence reason has no legitimate need for that
#: much room, and a smaller bound catches a runaway/malformed completion
#: sooner.
MAX_REASON_CHARS = 240

_SYSTEM_PROMPT = (
    "You are a sales assistant. Given a CRM contact's basic details, decide "
    "whether this lead is qualified. Never invent facts not present in the "
    "input. Respond with ONLY a single JSON object and no other text, with "
    'exactly these three string fields: "decision" (one of "qualified", '
    '"not_qualified", or "needs_more_info"), "reason" (a short, one-sentence '
    'explanation for the decision), and "qualification" (a brief '
    "human-readable lead-qualification note)."
)


def parse_qualify_lead_completion(raw_text: str) -> tuple[QualifyLeadDecision, str, str]:
    """Deterministically parse+validate the model's JSON completion into
    `(decision, reason, qualification)`. Raises `AIProviderError` for any
    deviation from the closed contract above -- never leaks the raw
    completion text into the error (mirrors
    `product/ai/openai_provider.py`'s own "type name and a short reason
    only" error-message discipline)."""
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AIProviderError(
            "model returned a completion that was not valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise AIProviderError("model returned a JSON completion that was not an object.")

    decision = parsed.get("decision")
    if decision not in _VALID_DECISIONS:
        raise AIProviderError(
            "model returned a completion with a missing or invalid 'decision'."
        )

    reason = parsed.get("reason")
    if not isinstance(reason, str) or not reason:
        raise AIProviderError(
            "model returned a completion with a missing or invalid 'reason'."
        )
    if len(reason) > MAX_REASON_CHARS:
        raise AIProviderError(f"model completion 'reason' exceeds {MAX_REASON_CHARS} characters.")

    qualification = parsed.get("qualification")
    if not isinstance(qualification, str) or not qualification:
        raise AIProviderError(
            "model returned a completion with a missing or invalid 'qualification'."
        )
    if len(qualification) > MAX_OUTPUT_CHARS:
        raise AIProviderError(
            f"model completion 'qualification' exceeds {MAX_OUTPUT_CHARS} characters."
        )

    return cast(QualifyLeadDecision, decision), reason, qualification


def build_lead_qualification_tool(provider: LLMProvider) -> ToolDefinition:
    async def _handler(
        context: ToolExecutionContext, payload: Mapping[str, object]
    ) -> dict[str, object]:
        contact_id = require_uuid(payload, "contact_id")
        contact = get_contact(context.agent_user_id, context.tenant_id, contact_id)
        user_content = (
            f"Name: {contact.first_name} {contact.last_name}\n"
            f"Email: {contact.email or 'unknown'}\n"
            f"Phone: {contact.phone or 'unknown'}\n"
        )
        completion = provider.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_content=user_content,
            max_output_chars=MAX_OUTPUT_CHARS,
        )
        decision, reason, qualification = parse_qualify_lead_completion(completion.text)
        return {
            "contact_id": str(contact.id),
            "qualification": qualification,
            "provider": completion.provider_name,
            "decision": decision,
            "reason": reason,
        }

    return ToolDefinition(
        key=TOOL_KEY,
        description="Draft a brief lead-qualification note for one CRM contact.",
        handler=_handler,
        required_scope_type="tenant",
        required_resource=CONTACT_RESOURCE,
        required_action="read",
        autonomy_tier=0,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=True,
    )


__all__ = [
    "MAX_REASON_CHARS",
    "TOOL_KEY",
    "QualifyLeadDecision",
    "build_lead_qualification_tool",
    "parse_qualify_lead_completion",
]
