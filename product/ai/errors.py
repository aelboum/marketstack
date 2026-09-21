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

import uuid


class AIValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an oversized prompt/transcript, an invalid confidence value) -- a
    400-shaped client error, never an authorization or provider failure."""


class AIProviderError(RuntimeError):
    """Raised by an `LLMProvider`/`SpeechProvider` implementation on
    failure -- mirrors `product.telephony.provider`'s/
    `product.conversations.sms`'s own normalized-error discipline (never a
    raw transport/SDK exception)."""


class AIAccessDeniedError(Exception):
    """Raised when `actor_user_id` does not hold the required
    `(resource, action)` capability at `tenant_id` -- gates this
    product's own tenant AI *policy* administration (Phase 9.4), never
    AI execution itself. Execution authorization remains entirely
    `control_plane`'s (`product/ai/invocation.py`); this error exists
    only because the policy table is Product-owned data needing a
    Product-owned RBAC gate, exactly as every other product module's own
    `*AccessDeniedError` does."""

    def __init__(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str
    ) -> None:
        self.actor_user_id = actor_user_id
        self.tenant_id = tenant_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for {action!r} on {resource!r} "
            f"in tenant {tenant_id}."
        )


class AIProviderNotConfiguredError(RuntimeError):
    """Raised when production AI execution is requested but no production
    LLM provider is configured (Phase 9.4). **This is the intended
    resting state of the system**, not a misconfiguration to work around:
    no AI vendor has been approved in this repository, so there is no
    production adapter to select, and the production path fails closed
    here rather than silently substituting the deterministic
    `FakeLLMProvider` (`product/ai/production.py`'s own module
    docstring)."""
