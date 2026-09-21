"""Tenant AI data policy resolution + platform provider eligibility
(docs/ROADMAP.md Phase 9.1's own "every tool touching tenant data passes
through Data Authorization (ADR-0013) before any content reaches an
external LLM provider -- no exceptions" requirement; **persisted** since
Phase 9.4).

**What changed in Phase 9.4.** Phases 9.1-9.3 shipped this module with
`resolve_tenant_ai_policy()` returning `None` for every tenant,
unconditionally -- a documented, deliberate default-deny, because
`control_plane.data_authorization` has no policy store of its own ("not a
persisted policy store (no table, no migration)... a future phase that
needs a real, persisted, tenant-editable policy store builds that against
this same typed shape"). Phase 9.4 is that future phase. The function now
reads `ai.tenant_policies` (`product/ai/models.py`) and resolves a real
`TenantAIDataPolicy` for a tenant that has been explicitly, auditably
configured.

**The default is unchanged, and that matters.** A tenant with no row, or
with `enabled=False`, still resolves to `None` -- which
`evaluate_data_authorization()`'s own first check treats as
`NO_TENANT_POLICY`, an unconditional deny. So nothing became permissive
by default; a tenant's AI posture only opens after someone holding
`ai.policy`/`manage` explicitly opened it, and that change is audited.

**A tenant can only ever narrow, never widen.** The resolved policy's
`allowed_providers` is intersected with the platform-wide
`PLATFORM_PROVIDER_POLICY` by Data Authorization itself (two separate
checks: `PROVIDER_NOT_GLOBALLY_ELIGIBLE` before
`PROVIDER_NOT_PERMITTED`), and `approved_capabilities` is validated
against `product/ai/capabilities.py`'s own closed production vocabulary
on every write. Neither is a free-text field a tenant can widen into
something the platform never approved.

**Platform-wide provider eligibility still names only `"fake"`**, and
that is still the honest state: no AI vendor has been approved in this
repository (`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 names SMS,
WhatsApp, telephony, and calendar sync -- not LLM). Production execution
does not become possible merely because a policy row now exists: it also
requires a configured production provider, and there is none --
`product/ai/production.py` fails closed on exactly that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from control_plane.data_authorization import ProviderEligibilityPolicy, TenantAIDataPolicy
from core.audit_log import ActorType, AuditOutcome, record
from infra.db import tenant_session_scope

from product.ai.capabilities import validate_capability
from product.ai.errors import AIValidationError
from product.ai.models import TenantAIPolicy
from product.ai.permissions import AI_POLICY_RESOURCE, require

PLATFORM_PROVIDER_POLICY = ProviderEligibilityPolicy(eligible_providers=frozenset({"fake"}))

#: The data classification every production capability operates on today.
#: `control_plane.data_authorization` validates this against its own
#: `VALID_DATA_CLASSIFICATIONS`; naming it once here keeps a tenant's
#: resolved policy from drifting from what the tools actually request.
TENANT_DATA_CLASSIFICATION = "tenant_data"

MAX_ALLOWED_PROVIDERS = 8


def resolve_tenant_ai_policy(tenant_id: uuid.UUID) -> TenantAIDataPolicy | None:
    """Resolve `tenant_id`'s persisted policy into the Control Plane's own
    typed shape, or `None` when the tenant has no policy or has it
    disabled -- which Data Authorization treats as an unconditional deny.

    Read fresh on every call, inside a tenant-scoped session: no caching,
    no module-level mutable state, no process-wide policy object. A policy
    revoked between one invocation and the next denies the next one."""
    with tenant_session_scope(tenant_id) as session:
        row = session.get(TenantAIPolicy, tenant_id)
        if row is None or not row.enabled:
            return None
        approved = tuple(str(c) for c in row.approved_capabilities)
        providers = tuple(str(p) for p in row.allowed_providers)

    if not approved or not providers:
        # An enabled policy approving nothing is not a usable policy --
        # resolving it to None keeps "enabled but empty" from looking
        # different, to Data Authorization, than "not configured."
        return None

    return TenantAIDataPolicy(
        tenant_id=tenant_id,
        allowed_data_classifications=frozenset({TENANT_DATA_CLASSIFICATION}),
        allowed_purposes=frozenset(approved),
        allowed_providers=frozenset(providers),
    )


@dataclass(frozen=True, slots=True)
class TenantAIPolicyView:
    tenant_id: uuid.UUID
    enabled: bool
    approved_capabilities: tuple[str, ...]
    allowed_providers: tuple[str, ...]
    updated_by_user_id: uuid.UUID
    updated_at: datetime


def _to_view(row: TenantAIPolicy) -> TenantAIPolicyView:
    return TenantAIPolicyView(
        tenant_id=row.tenant_id,
        enabled=row.enabled,
        approved_capabilities=tuple(str(c) for c in row.approved_capabilities),
        allowed_providers=tuple(str(p) for p in row.allowed_providers),
        updated_by_user_id=row.updated_by_user_id,
        updated_at=row.updated_at,
    )


def get_tenant_ai_policy(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> TenantAIPolicyView | None:
    """Read `tenant_id`'s own policy. `None` when none is configured --
    never another tenant's row: the lookup runs inside
    `tenant_session_scope()`, so RLS makes a different tenant's policy
    unreachable rather than merely filtered."""
    require(actor_user_id, tenant_id, resource=AI_POLICY_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(TenantAIPolicy, tenant_id)
        if row is None:
            return None
        session.expunge(row)
    return _to_view(row)


def set_tenant_ai_policy(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    enabled: bool,
    approved_capabilities: tuple[str, ...] = (),
    allowed_providers: tuple[str, ...] = (),
) -> TenantAIPolicyView:
    """Create or replace `tenant_id`'s own AI policy, audited.

    Every capability is validated against the closed production
    vocabulary (`product/ai/capabilities.py`) before anything is written,
    so an unknown or misspelled capability is rejected rather than
    persisted -- fail closed on unknown capabilities, never "store it and
    find out at execution time". Providers are likewise bounded and must
    be platform-eligible: a tenant can narrow what the platform allows,
    never widen it."""
    require(actor_user_id, tenant_id, resource=AI_POLICY_RESOURCE, action="manage")

    capabilities = tuple(dict.fromkeys(approved_capabilities))
    for capability in capabilities:
        validate_capability(capability)

    providers = tuple(dict.fromkeys(allowed_providers))
    if len(providers) > MAX_ALLOWED_PROVIDERS:
        raise AIValidationError(f"at most {MAX_ALLOWED_PROVIDERS} providers may be listed.")
    for provider in providers:
        if provider not in PLATFORM_PROVIDER_POLICY.eligible_providers:
            raise AIValidationError(
                f"{provider!r} is not a platform-eligible AI provider "
                f"(eligible: {sorted(PLATFORM_PROVIDER_POLICY.eligible_providers)})."
            )

    with tenant_session_scope(tenant_id) as session:
        row = session.get(TenantAIPolicy, tenant_id)
        if row is None:
            row = TenantAIPolicy(tenant_id=tenant_id, updated_by_user_id=actor_user_id)
            session.add(row)
        row.enabled = enabled
        row.approved_capabilities = list(capabilities)
        row.allowed_providers = list(providers)
        row.updated_by_user_id = actor_user_id
        session.flush()
        session.refresh(row)
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="ai.policy.updated",
        resource_type="ai.policy",
        resource_id=str(tenant_id),
        outcome=AuditOutcome.SUCCESS,
        # Bounded decision context only -- capability keys and provider
        # names are short, non-sensitive identifiers. No prompt, no model
        # output, no tenant record content is ever audited here.
        metadata={
            "enabled": enabled,
            "approved_capabilities": sorted(capabilities),
            "allowed_providers": sorted(providers),
        },
    )
    return _to_view(row)


__all__ = [
    "MAX_ALLOWED_PROVIDERS",
    "PLATFORM_PROVIDER_POLICY",
    "TENANT_DATA_CLASSIFICATION",
    "TenantAIPolicyView",
    "get_tenant_ai_policy",
    "resolve_tenant_ai_policy",
    "set_tenant_ai_policy",
]
