"""`resolve_tenant_ai_policy()`/`PLATFORM_PROVIDER_POLICY` -- the
disclosed default-deny state (docs/ROADMAP.md Phase 9.1). No database --
a plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

import uuid

from product.ai.policy import PLATFORM_PROVIDER_POLICY, resolve_tenant_ai_policy


def test_resolve_tenant_ai_policy_always_returns_none() -> None:
    assert resolve_tenant_ai_policy(uuid.uuid4()) is None
    assert resolve_tenant_ai_policy(uuid.uuid4()) is None


def test_platform_provider_policy_only_allows_fake() -> None:
    assert PLATFORM_PROVIDER_POLICY.eligible_providers == frozenset({"fake"})
