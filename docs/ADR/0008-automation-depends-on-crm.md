# ADR-0008: Automation May Depend on CRM (One-Directional)

Status: ACCEPTED
Date: 2026-09-20

## Context

`docs/ROADMAP.md` Phase 10.2's own action library includes "create task,
update contact, move opportunity" — each a live, current write against
CRM's own tenant-owned tables. Mirrors `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`'s
already-established reasoning exactly: this is not a generic,
domain-agnostic capability (foundation-promotable) and not a reaction to
a discrete state-change event (it *is* the state change), so it needs
the same direct, re-authorizing read/write path CRM already grants
Marketing and Appointments.

## Decision

1. `product.automation` MAY import `product.crm`'s own published service
   functions (`product.crm.activities.create_task()`,
   `product.crm.contacts.update_contact()`,
   `product.crm.opportunities.change_stage()`) — never `product.crm
   .models` directly, and never any other product module's internals.
   `product.crm` may NEVER import `product.automation`.
2. Every one of these calls passes the **workflow's own
   `created_by_user_id`** as `actor_user_id` — `product.crm`'s own
   `require()`/`core.rbac.can()` check inside each function is the real
   authorization boundary, re-evaluated at every single execution, never
   cached or assumed from workflow-creation time. This is the direct
   mechanism behind `docs/ROADMAP.md` Phase 10.2's own explicit security
   requirement: "an automation action must never be able to exceed the
   permissions of the tenant user who configured it."
3. `product.automation` remains independent from every other product
   module. Enforced by `pyproject.toml`: `"product.automation"` removed
   from the blanket independence contract's `modules` list, a new
   `forbidden` contract (`source_modules = ["product.automation"]`,
   forbidden every product module except `product.crm`), and one
   `layers` contract (`product.automation` -> `product.crm`).

## Consequences

`product/automation/actions.py` imports exactly the three CRM functions
above. `send_email`/`send_webhook` actions need no product-module
dependency at all (`core.email`, and a Product-owned, SSRF-hardened HTTP
client respectively — see `product/automation/actions.py`'s own
docstring).
