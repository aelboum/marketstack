"""Approval Inbox: the product-facing surface over SaaS-OS's own
tier>=1 human-approval workflow (docs/ROADMAP.md Phase 29).

**No second approval system.** This module owns no persistence of its
own -- there is no `product/approvals/models.py`, no
`approvals.approval_requests` schema, no migration. Every read and every
state transition (`propose_action()`, `get_approval()`,
`list_approvals()`, `approve()`, `reject()`, `execute_approved()`) is the
real, installed `control_plane.approvals` function, called directly, with
its own real `ApprovalRequest` row (`control_plane.approval_requests`,
already RLS-protected by SaaS-OS) as the one and only source of truth.
This module adds exactly two things `control_plane.approvals` does not
provide on its own:

1. **A product-defined authorization gate.** Read directly:
   `control_plane.approvals.service`'s own `get_approval()`/
   `list_approvals()`/`approve()`/`reject()` perform tenant-scoping and
   the self-approval separation-of-duties check, but no
   `core.rbac.can()` permission check at all -- by design, the same
   "product defines its own permission names, Core's own mechanism
   evaluates them" split `docs/RESPONSIBILITY-MATRIX.md` §"Tenancy,
   Identity, Authorization" already documents for every other product
   permission. `product/approvals/permissions.py::require()` is that
   gate, mirroring `product/appointments/permissions.py`'s own shape
   exactly -- it is the product's own authorization boundary sitting in
   front of an already-real mechanism, not a competing one.
2. **Business-language presentation.** `product/approvals/labels.py`
   translates a raw `tool_key` (e.g. `"ai.crm.qualify_lead"`) and a raw
   `status` string into the business-facing labels
   `docs/ROADMAP.md` Phase 29 requires -- a small, static, maintainable
   map, never a generic translation framework.

**Dependency direction**: `product.approvals` depends on nothing else in
`product/` -- not `product.ai` (which defines the `tool_key` strings this
module's label map merely duplicates as small, static presentation
strings, the same "duplicate a tiny genuinely-shared value rather than
add a cross-module edge" judgment call `product/appointments/pagination.py`
already recorded) and not any other domain module. Nothing may depend on
`product.approvals` either -- it is a pure composition/adapter layer, the
literal Phase 29 principle: "do not build a new approval system, compose
the existing one."

**This module's router (`product/approvals/routes.py::router`) is wired
into `product/api/main.py`** (the Phase 29 final-wiring pass, once the
`product/api/main.py` protection lifted) -- `app.include_router(approvals_router)`
alongside every other product router, and
`from product.approvals import event_handlers as _approvals_event_handlers  # noqa: F401`
alongside every other module's own import-time `subscribe()` side
effect, both following the exact same pattern
`product/templates/__init__.py`'s own module docstring already
documented as the eventual follow-up. No purge participant is
registered for this module -- it owns no table of its own (see this
docstring's own opening section), so there is nothing for a tenant purge
to remove.

The HTTP API (`/v1/approvals/...`) is now reachable through the real,
running application, and the `owner`/`member` permission grants in
`event_handlers.py` are now automatically provisioned for a newly-created
role via the real `agency.role_provisioned` event, exactly like every
other module's own grants.
"""
