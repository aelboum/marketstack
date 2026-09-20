"""Tenant AI data policy resolution + platform provider eligibility
(docs/ROADMAP.md Phase 9.1's own "every tool touching tenant data passes
through Data Authorization (ADR-0013) before any content reaches an
external LLM provider -- no exceptions" requirement).

**No persisted tenant policy store exists, and this phase does not build
one** -- `control_plane.data_authorization`'s own module docstring is
explicit that `TenantAIDataPolicy` is "not a persisted policy store (no
table, no migration)... a future phase that needs a real, persisted,
tenant-editable policy store builds that against this same typed shape;
this phase does not invent one speculatively." `product.ai` inherits that
same boundary unchanged: `resolve_tenant_ai_policy()` below always returns
`None` for every tenant today, which -- per `control_plane
.data_authorization.evaluate_data_authorization()`'s own first
unconditional check -- means every single Data Authorization request this
product's tools make is DENIED by default, structurally, not by omission.
This is the disclosed, intentional state of the system until a later
phase adds real tenant-configurable AI policy: **no tenant data can reach
an LLM provider through any tool in this codebase today**, which is
exactly the "do not create a fake production default" boundary the
Fake-only `LLMProvider` (`product/ai/provider.py`) already enforces one
layer further in.

**Platform-wide provider eligibility mirrors the same "no real vendor"
reality**: `PLATFORM_PROVIDER_POLICY` below names only `"fake"` as
globally eligible -- there is no real LLM vendor for a tenant policy to
ever widen into, so `DataDenialReason.PROVIDER_NOT_GLOBALLY_ELIGIBLE` is
the only reachable outcome for any real provider name, by construction,
until a real vendor is selected and added here explicitly.
"""

from __future__ import annotations

import uuid

from control_plane.data_authorization import ProviderEligibilityPolicy, TenantAIDataPolicy

PLATFORM_PROVIDER_POLICY = ProviderEligibilityPolicy(eligible_providers=frozenset({"fake"}))


def resolve_tenant_ai_policy(tenant_id: uuid.UUID) -> TenantAIDataPolicy | None:
    """Always `None` -- see module docstring. `tenant_id` is accepted (not
    ignored via `*args`) so a future real implementation's call sites
    never need to change, only this function's body."""
    return None


__all__ = ["PLATFORM_PROVIDER_POLICY", "resolve_tenant_ai_policy"]
