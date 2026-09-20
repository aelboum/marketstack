"""The workflow-ID-prefix tenant-scoping strategy
(`product/automation/durable/client.py`'s own docstring) -- pure unit
tests, no Temporal server, no network.

Includes a regression test for a real tenant-identity-confusion bug
found and fixed during this spike's own manual security review: a bare
`str.startswith()` prefix check would let a `tenant_id` containing its
own `:` collide with a shorter tenant's own prefix.
"""

from __future__ import annotations

from product.automation.durable.client import (
    _workflow_id_for_tenant,
    _workflow_id_pattern_for_tenant,
)


def test_workflow_id_for_tenant_is_matched_by_its_own_pattern() -> None:
    workflow_id = _workflow_id_for_tenant("spike-tenant-1")
    assert _workflow_id_pattern_for_tenant("spike-tenant-1").match(workflow_id)


def test_workflow_id_for_one_tenant_does_not_match_a_different_tenants_pattern() -> None:
    workflow_id = _workflow_id_for_tenant("spike-tenant-1")
    assert not _workflow_id_pattern_for_tenant("spike-tenant-2").match(workflow_id)


def test_crafted_tenant_id_with_embedded_colon_does_not_collide_with_shorter_tenant() -> None:
    """The bug this test guards against: a bare prefix check
    (`str.startswith("automation-durable-probe:a:")`) would wrongly
    match a workflow id minted for `tenant_id="a:evil"`
    (`"automation-durable-probe:a:evil:<hex>"` does start with that
    string) when listing/terminating for tenant `"a"`. The anchored
    pattern must not."""
    colliding_workflow_id = _workflow_id_for_tenant("a:evil")
    assert not _workflow_id_pattern_for_tenant("a").match(colliding_workflow_id)
    assert _workflow_id_pattern_for_tenant("a:evil").match(colliding_workflow_id)


def test_tenant_id_with_regex_metacharacters_is_treated_literally() -> None:
    """`tenant_id` is interpolated into a regex pattern
    (`_workflow_id_pattern_for_tenant()`) -- it must be escaped, not
    treated as regex syntax, or a crafted `tenant_id` could widen its own
    match beyond its own workflows."""
    workflow_id = _workflow_id_for_tenant("tenant.*")
    assert _workflow_id_pattern_for_tenant("tenant.*").match(workflow_id)
    # If `.` were live regex syntax (not escaped), this unrelated tenant
    # id would also match "tenant" + any-character + "*" style patterns.
    assert not _workflow_id_pattern_for_tenant("tenantX").match(workflow_id)
