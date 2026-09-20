"""`ai.conversations.suggest_reply` tool (docs/ROADMAP.md Phase 9.3).

Drafts a suggested reply for one Conversations thread -- **never sends
it**. The handler's own output is a draft string only; nothing in this
module calls `product.conversations.messages.create_message()` or any
other mutating function -- a human always sends, matching Phase 9.3's own
explicit Acceptance Criteria ("a drafted reply never sends without
explicit human action"). Mirrors `product/ai/tools
/conversation_summarization.py`'s exact shape/reasoning otherwise (same
bounded message window, same `THREAD_RESOURCE`/`"read"` permission --
drafting a reply needs only read access to the thread it drafts for).
"""

from __future__ import annotations

from collections.abc import Mapping

from control_plane.orchestration import ToolDefinition, ToolExecutionContext

from product.ai.provider import MAX_OUTPUT_CHARS, LLMProvider
from product.ai.tools.conversation_summarization import MAX_MESSAGES
from product.ai.validation import require_uuid
from product.conversations.messages import list_messages
from product.conversations.permissions import THREAD_RESOURCE

TOOL_KEY = "ai.conversations.suggest_reply"

_SYSTEM_PROMPT = (
    "You are a support assistant drafting a reply suggestion for a human "
    "agent to review. This is a DRAFT ONLY -- it is never sent "
    "automatically. Never invent facts not present in the input."
)


def build_suggested_reply_tool(provider: LLMProvider) -> ToolDefinition:
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
            "draft_reply": completion.text,
            "sent": False,
            "provider": completion.provider_name,
        }

    return ToolDefinition(
        key=TOOL_KEY,
        description="Draft a suggested reply for one Conversations thread. Never sends it.",
        handler=_handler,
        required_scope_type="tenant",
        required_resource=THREAD_RESOURCE,
        required_action="read",
        autonomy_tier=0,
        data_classification="tenant_data",
        side_effect="read_only",
        requires_data_authorization=True,
    )


__all__ = ["TOOL_KEY", "build_suggested_reply_tool"]
