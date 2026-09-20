"""Product-owned exceptions for `product/ai/` (docs/ROADMAP.md Phase 9).

Deliberately narrow -- most of the authorization/authority surface this
module needs already exists (`control_plane.orchestration`'s own
`UnauthorizedToolInvocationError`/`TierRequiresApprovalError`/
`DataAuthorizationRequiredError`/`ToolExecutionError`, all reused
directly, never re-caught-and-rethrown as a Product-local equivalent --
docs/ROADMAP.md Phase 9's own "do not create Product-local equivalents of
SaaS-OS AI authorization" requirement). Only the errors below have no
existing SaaS-OS counterpart.
"""

from __future__ import annotations


class AIValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an oversized prompt/transcript, an invalid confidence value) -- a
    400-shaped client error, never an authorization or provider failure."""


class AIProviderError(RuntimeError):
    """Raised by an `LLMProvider`/`SpeechProvider` implementation on
    failure -- mirrors `product.telephony.provider`'s/
    `product.conversations.sms`'s own normalized-error discipline (never a
    raw transport/SDK exception)."""
