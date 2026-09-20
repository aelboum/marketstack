"""`ai.crm.suggest_next_actions` tool (docs/ROADMAP.md Phase 9.1).

Reads one `crm.opportunities` row (`product.crm.opportunities.get_opportunity()`)
and asks the injected `LLMProvider` for suggested next actions. Mirrors
`product/ai/tools/lead_qualification.py`'s exact shape -- see that
module's own docstring for the shared reasoning (tier 0, read-only,
`tenant_data`, Data-Authorization-gated, `required_resource`/
`required_action` reused verbatim from the underlying CRM permission).
"""

from __future__ import annotations

from collections.abc import Mapping

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.validation import require_uuid
from product.crm.opportunities import get_opportunity
from product.crm.permissions import OPPORTUNITY_RESOURCE

TOOL_KEY = "ai.crm.suggest_next_actions"

_SYSTEM_PROMPT = (
    "You are a sales assistant. Given a CRM opportunity's current stage "
    "and amount, suggest 1-3 concrete next actions. Never invent facts "
    "not present in the input."
)


def build_suggested_next_actions_tool(provider: LLMProvider) -> ToolDefinition:
    async def _handler(
        context: ToolExecutionContext, payload: Mapping[str, object]
    ) -> dict[str, object]:
        opportunity_id = require_uuid(payload, "opportunity_id")
        opportunity = get_opportunity(context.agent_user_id, context.tenant_id, opportunity_id)
        user_content = (
            f"Opportunity: {opportunity.name}\n"
            f"Stage id: {opportunity.stage_id}\n"
            f"Amount: {opportunity.amount if opportunity.amount is not None else 'unknown'}\n"
        )
        completion = provider.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_content=user_content,
            max_output_chars=MAX_OUTPUT_CHARS,
        )
        return {
            "opportunity_id": str(opportunity.id),
            "suggested_next_actions": completion.text,
            "provider": completion.provider_name,
        }

    return ToolDefinition(
        key=TOOL_KEY,
        description="Suggest next actions for one CRM opportunity.",
        handler=_handler,
        required_scope_type="tenant",
        required_resource=OPPORTUNITY_RESOURCE,
        required_action="read",
        autonomy_tier=0,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=True,
    )


__all__ = ["TOOL_KEY", "build_suggested_next_actions_tool"]
