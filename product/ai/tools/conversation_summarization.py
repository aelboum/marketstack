"""`ai.conversations.summarize` tool (docs/ROADMAP.md Phase 9.1).

Reads a bounded window of one `conversations.messages` thread
(`product.conversations.messages.list_messages()`, most-recent
`MAX_MESSAGES` only -- never the entire history unbounded) and asks the
injected `LLMProvider` for a summary. Mirrors `product/ai/tools
/lead_qualification.py`'s exact shape/reasoning; `required_resource`/
`required_action` reused verbatim from `THREAD_RESOURCE`/`"read"`
(`list_messages()` itself already gates on this same pair).
"""

from __future__ import annotations

from collections.abc import Mapping

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.validation import require_uuid
from product.conversations.messages import list_messages
from product.conversations.permissions import THREAD_RESOURCE

TOOL_KEY = "ai.conversations.summarize"

MAX_MESSAGES = 20

_SYSTEM_PROMPT = (
    "You are a support assistant. Summarize the following conversation "
    "thread in a few sentences. Never invent facts not present in the "
    "input."
)


def build_conversation_summarization_tool(provider: LLMProvider) -> ToolDefinition:
    async def _handler(
        context: ToolExecutionContext, payload: Mapping[str, object]
    ) -> dict[str, object]:
        thread_id = require_uuid(payload, "thread_id")
        messages = list_messages(
            context.agent_user_id, context.tenant_id, thread_id, limit=MAX_MESSAGES
        )
        lines = [f"[{m.direction}] {m.body}" for m in messages if not m.is_internal_note]
        user_content = "\n".join(lines) if lines else "(no messages)"
        completion = provider.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_content=user_content,
            max_output_chars=MAX_OUTPUT_CHARS,
        )
        return {
            "thread_id": str(thread_id),
            "message_count": len(messages),
            "summary": completion.text,
            "provider": completion.provider_name,
        }

    return ToolDefinition(
        key=TOOL_KEY,
        description="Summarize the most recent messages in one Conversations thread.",
        handler=_handler,
        required_scope_type="tenant",
        required_resource=THREAD_RESOURCE,
        required_action="read",
        autonomy_tier=0,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=True,
    )


__all__ = ["MAX_MESSAGES", "TOOL_KEY", "build_conversation_summarization_tool"]
