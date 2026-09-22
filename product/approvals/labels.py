"""Business-language presentation for `product/approvals/`
(docs/ROADMAP.md Phase 29). A small, static, maintainable map -- never a
generic translation framework (Phase 29's own explicit scope limit).

**Action labels**: `control_plane.approval_requests.tool_key` is a raw,
dotted tool identifier (`"ai.crm.qualify_lead"`) -- never shown to a
business user as-is. Every `tool_key` any `product/ai/tools/*.py` module
currently defines is listed here (none is yet registered at
`autonomy_tier >= 1`, so none has ever actually reached this module in
production -- see `product/approvals/__init__.py`'s own docstring and
this phase's own report). An unrecognized future `tool_key` (a tool this
map has not been updated for yet) falls back to a readable, honestly
generic label derived from the key itself, never a raw dotted string.

**Status labels**: `control_plane.approval_requests.status` is exactly
one of `"pending"`/`"approved"`/`"rejected"`/`"executing"`/`"executed"`
(`control_plane/approvals/models.py`'s own docstring) -- there is no
persisted `"failed"` status: `execute_approved()` reverts a failed
execution attempt back to `"approved"` so a retry remains possible
(`control_plane/approvals/service.py::execute_approved()`'s own
docstring). This map covers exactly those five real values -- adding a
sixth label here without a sixth real status value would be inventing
state the backend does not have.
"""

from __future__ import annotations

import re

_ACTION_LABELS: dict[str, str] = {
    "ai.crm.qualify_lead": "Lead kwalificeren",
    "ai.crm.suggest_next_actions": "Volgende actie voorstellen",
    "ai.conversations.summarize": "Gesprek samenvatten",
    "ai.conversations.suggest_reply": "Antwoord opstellen",
}

_FALLBACK_WORD_RE = re.compile(r"[._]+")


def action_label(tool_key: str) -> str:
    """A business-readable label for `tool_key`. Falls back to a plain,
    honest rendering of the key itself (never a raw dotted string) for
    any tool this map has not been updated for yet -- e.g.
    `"ai.crm.do_something_new"` becomes `"Ai crm do something new"`,
    legible without pretending to know more about it than that."""
    known = _ACTION_LABELS.get(tool_key)
    if known is not None:
        return known
    words = _FALLBACK_WORD_RE.sub(" ", tool_key).strip()
    return words[:1].upper() + words[1:] if words else tool_key


_STATUS_LABELS: dict[str, str] = {
    "pending": "Wacht op goedkeuring",
    "approved": "Goedgekeurd",
    "rejected": "Afgewezen",
    "executing": "Wordt uitgevoerd",
    "executed": "Uitgevoerd",
}


def status_label(status: str) -> str:
    """A business-readable label for `status`. Raises `KeyError` for
    anything outside the five real values this map covers -- a caller
    passing an unrecognized status has a real bug to find, not something
    to paper over with a generic fallback (unlike `action_label()`, where
    an unrecognized *tool* is an expected, forward-compatible case)."""
    return _STATUS_LABELS[status]


GENERIC_APPROVAL_REASON = (
    "Deze actie vereist menselijke goedkeuring omdat ze een aanzienlijke "
    "of moeilijk terug te draaien invloed heeft op uw bedrijf."
)
"""The one honest thing this product can say about *why* any given
approval exists: `control_plane.approval_requests` carries no free-text
reason field of its own (only `tool_key`/`payload`/`agent_scope_value`,
`control_plane/approvals/models.py`) -- so every approval shows this same
true, general statement of policy (why tier>=1 exists at all) rather than
a fabricated, request-specific explanation the data does not actually
contain (docs/ROADMAP.md Phase 29's own "do not invent explanations"
rule)."""

__all__ = ["GENERIC_APPROVAL_REASON", "action_label", "status_label"]
