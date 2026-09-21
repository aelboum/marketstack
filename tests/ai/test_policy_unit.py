"""`PLATFORM_PROVIDER_POLICY` -- the platform-wide provider eligibility
list (docs/ROADMAP.md Phase 9.1). No database -- a plain unit test, part
of the default `pytest` run.

**`resolve_tenant_ai_policy()` is no longer asserted here.** Phase 9.1
shipped it as an unconditional `return None`, which a no-database unit
test could assert directly. Phase 9.4 made it read the persisted
`ai.tenant_policies` row, so it now performs real tenant-scoped database
I/O and cannot belong in the default, database-free suite -- keeping the
assertion here would have made the default `pytest` run silently require
a database.

The behaviour itself is not less covered, it is better covered:
`tests/ai/test_production_policy_integration.py` asserts the same
default-deny outcome against a real tenant with no policy row, and adds
the cases a stubbed `None` could never reach -- a disabled policy, an
enabled-but-empty policy, cross-tenant isolation, and revocation taking
effect on the next invocation.
"""

from __future__ import annotations

from product.ai.policy import PLATFORM_PROVIDER_POLICY


def test_platform_provider_policy_only_allows_fake() -> None:
    """No real LLM vendor has been approved for this product, so `"fake"`
    remains the only globally eligible provider -- and a tenant policy can
    only ever narrow this list, never widen it
    (`product/ai/policy.py`'s own module docstring)."""
    assert PLATFORM_PROVIDER_POLICY.eligible_providers == frozenset({"fake"})
