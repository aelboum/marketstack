"""`ai.crm.qualify_lead` tool (docs/ROADMAP.md Phase 9.1).

Reads one `crm.contacts` row (`product.crm.contacts.get_contact()`, the
same read `docs/ADR/0006-ai-depends-on-crm-conversations-telephony.md`
sanctions) and asks the injected `LLMProvider` to produce a qualification
summary. Tier 0 (direct-invocation), read-only side effect, `tenant_data`
classification, Data-Authorization-gated -- see `product/ai/provider.py`'s
own module docstring for why the completion this phase can actually
produce is a deterministic Fake marker, never real qualification
prose.

**`required_resource`/`required_action` reuse `crm.contact`/`read`
verbatim** -- an invoking agent that cannot already read this contact via
ordinary CRM access cannot qualify it via this tool either (ADR-0006's
own "defense in depth, not a new authorization path" point).
"""

from __future__ import annotations

from collections.abc import Mapping

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.validation import require_uuid
from product.crm.contacts import get_contact
from product.crm.permissions import CONTACT_RESOURCE

TOOL_KEY = "ai.crm.qualify_lead"

_SYSTEM_PROMPT = (
    "You are a sales assistant. Given a CRM contact's basic details, "
    "produce a brief lead-qualification note. Never invent facts not "
    "present in the input."
)


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
        return {
            "contact_id": str(contact.id),
            "qualification": completion.text,
            "provider": completion.provider_name,
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


__all__ = ["TOOL_KEY", "build_lead_qualification_tool"]
