"""Reacts to `agency.role_provisioned` (published by `product/agency
/roles.py`) to grant this module's own `billing.resale_plan`/
`billing.subscription` permissions to the newly provisioned role, and to
`platform.role_provisioned` (B2B2C Billing Foundation, Step 2) to
provision the platform tenant's own commercial `MerchantAccount`
(`product/billing/parties.py`) -- the "module needing another module's
capability reacts via the event dispatcher" path `docs/ARCHITECTURE.md`
section 2.2 prescribes for exactly this case. `product.billing` never
imports `product.agency` or `product.platform` directly, the same rule
every other module's own `event_handlers.py` already follows.

**Role name is generic on purpose**: `product/agency/roles.py` provisions
`"owner"`/`"member"` for every tenant this product creates (agencies and
their clients alike, `docs/ADR/0012-...`'s own "Direct Platform Client and
Agency are the same structural case" reasoning) -- so the permission
grants below apply identically to both an agency's own root role and a
client's own role, with no special-casing.

`owner`: full control over its own tenant's resale catalog (`create`,
`read`, `update`, `deactivate`) plus full subscription lifecycle
(`create`, `read`, `update`, `cancel`) plus `billing.catalog:manage`
(Step 4 below). `member`: `read`-only on the resale catalog (viewing
tiers, never defining pricing -- a revenue-critical decision reserved for
`owner`, mirroring `product/reputation/event_handlers.py`'s own "cancel
is owner-only" precedent, now also the reason `billing.catalog:manage` is
`owner`-only) plus `create`/`read`/`update` on subscriptions, never
`cancel`.

**`billing.catalog:read`/`:manage` (Catalog v2 Owned Plans & Offers, Step
4)** is the frozen contract's own `billing.catalog` resource (`core
/billing/authorization.py`'s own vocabulary table) -- `manage` is what
`core.billing.catalog.create_owned_plan()`/`create_plan_offer()`/
`set_plan_visibility()`/`withdraw_plan()`/`revoke_plan_offer()` all
authorize against on the owner tenant internally; `read` is what
`core.billing.evaluate_plan_eligibility()`'s own `private`-visibility
rule consults (`can(caller, owner, billing.catalog:read)`) -- without it
an owner could create a `private` plan and never see it eligible even for
its own tenant. Both granted to `owner` only, for the identical "defining
commercial terms is revenue-critical" reason `RESALE_PLAN_RESOURCE`'s own
`create`/`update`/`deactivate` actions already are.

**`billing.account:charge` (B2B2C Sponsored Subscriptions, Step 3)** is
granted to both `owner` and `member` at their own tenant, for the
identical reason `billing.subscription:create` already is: it is the
*payer*-side half of `core.billing.commercial.create_subscription()`'s
own dual authorization (`product/billing/permissions.py`'s own module
docstring; `core/billing/authorization.py`'s own vocabulary table, read
directly against the frozen SHA). Granted here, scoped to the grantee's
own tenant exactly like every other grant in this file, it reaches a
descendant only through that tenant's own pre-existing `SUBTREE` role
reach (`product/agency/provisioning.py::provision_agency()`'s own grant)
-- never through any new hierarchy-walk logic added here. This is what
lets an agency's own owner use the agency's own `BillingAccount` as payer
for a sponsored client subscription, and a client's own member use the
client's own `BillingAccount` for its own self-pay -- and nothing more:
neither can ever reach an unrelated tenant's `BillingAccount`, since
`can()`'s own `SUBTREE` semantics never cross from one tenant's subtree
into an unrelated one (`product/billing/commercial_subscriptions.py`'s
own module docstring covers the full authorization model).

**Agency merchant provisioning is deliberately NOT wired here, unlike
the platform's.** `product/billing/parties.py::_ensure_agency_merchant_account()`
exists as an internal, idempotent provisioning primitive (Phase 2D) --
it is NOT subscribed to `agency.role_provisioned`. `provision_agency()`
is called by essentially every integration test in this repository, in
every `tests/*/_cleanup.py` module's own tenant-teardown path (not only
`tests/agency/`/`tests/billing/`'s own, already extended for this exact
table) -- reactively creating a `core.billing_merchant_accounts` row on
every single one would require extending every one of those unrelated
cleanup helpers too, far outside this phase's own scope (confirmed
empirically: wiring it this way broke `tests/agency/*` and
`tests/platform/*`'s own pre-existing, unrelated cleanup with a foreign-key
violation on tenant deletion). `bootstrap_platform_tenant()`, by contrast,
has exactly one call shape in the whole repository (the `platform`
fixture in `tests/platform/test_*_integration.py` and this module's own
`tests/billing/test_commercial_parties_integration.py`) -- both already
extended for this table -- so the platform case stays reactively wired
(Phase 2C's own "prefer extending an existing... provisioning mechanism"
instruction), while the agency case stays callable-only, never automatic
(Phase 2D asks for "an explicit provisioning function," not automatic
wiring)."""

from __future__ import annotations

import uuid

from core.rbac import get_role

from product.billing.parties import _ensure_platform_merchant_account
from product.billing.permissions import (
    BILLING_ACCOUNT_RESOURCE,
    BILLING_CATALOG_RESOURCE,
    RESALE_PLAN_RESOURCE,
    SUBSCRIPTION_RESOURCE,
    grant_to_role,
)
from product.foundation.events import Event, subscribe

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"
_PLATFORM_OWNER_ROLE_NAME = "platform_owner"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (RESALE_PLAN_RESOURCE, ("create", "read", "update", "deactivate")),
    (SUBSCRIPTION_RESOURCE, ("create", "read", "update", "cancel")),
    (BILLING_ACCOUNT_RESOURCE, ("charge",)),
    (BILLING_CATALOG_RESOURCE, ("read", "manage")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (RESALE_PLAN_RESOURCE, ("read",)),
    (SUBSCRIPTION_RESOURCE, ("create", "read", "update")),
    (BILLING_ACCOUNT_RESOURCE, ("charge",)),
)


def _handle_agency_role_provisioned(event: Event) -> None:
    role_name = event.payload.get("role_name")
    if role_name not in (_OWNER_ROLE_NAME, _MEMBER_ROLE_NAME):
        return
    tenant_id = uuid.UUID(event.tenant_id)
    role_id = uuid.UUID(str(event.payload["role_id"]))
    role = get_role(tenant_id, role_id)
    grants = _OWNER_GRANTS if role_name == _OWNER_ROLE_NAME else _MEMBER_GRANTS
    for resource, actions in grants:
        grant_to_role(tenant_id, role, resource=resource, actions=actions)


def _handle_platform_role_provisioned(event: Event) -> None:
    """This is the one authorized internal provisioning flow
    `_ensure_platform_merchant_account()` exists for (that function's own
    docstring, "Trust boundary") -- `event.tenant_id` is never
    caller-controlled input, it is the tenant `bootstrap_platform_tenant()`
    itself just created."""
    if event.payload.get("role_name") != _PLATFORM_OWNER_ROLE_NAME:
        return
    _ensure_platform_merchant_account(uuid.UUID(event.tenant_id))


subscribe("agency.role_provisioned", _handle_agency_role_provisioned)
subscribe("platform.role_provisioned", _handle_platform_role_provisioned)
