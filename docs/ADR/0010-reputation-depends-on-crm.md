# ADR-0010: Reputation May Depend on CRM (One-Directional)

Status: ACCEPTED
Date: 2026-09-21

## Context

`docs/ROADMAP.md` Phase 12.1's own Objective is "trigger a review request
(manually or via Automation), track its status." A review request has no
target without a real customer to send it to, and the repository already has
exactly one system of record for a customer's identity and contact
information: `crm.contacts` (Phase 4.1). Building a second, Reputation-owned
"who is this customer" record would be precisely the fragmented-identity
outcome `docs/ADR/0005-...`'s own Rejected Alternative section already
argues against for Appointments, applied here for the identical reason: the
same person who is a CRM contact today must not become two unrelated rows
(one in `crm.contacts`, one in a new `reputation.customers` table) with no
deduplication.

`docs/ARCHITECTURE.md` §2.2 offers exactly two sanctioned paths for one
module needing another's capability: promote a genuinely generic capability
to `product/foundation/`, or react to another module's state change via the
event dispatcher. Neither fits: resolving "does this contact exist in this
tenant, and what is their email address" is not a domain-agnostic capability,
and it is not a reaction to a discrete past event -- a review request needs
the contact's *current* email address at send time, not a stream of past
`crm.contact.created`/`crm.contact.updated` events to reconstruct it from.
This is the same shape `docs/ADR/0005-...` (Marketing/Appointments -> CRM),
`docs/ADR/0006-...` (AI -> CRM/Conversations/Telephony), `docs/ADR/0008-...`
(Automation -> CRM), and `docs/ADR/0009-...` (Websites -> White-Label)
already named and resolved for their own, separately-justified single
dependency edge.

## Decision

1. `product.reputation` MAY import `product.crm`'s own published service
   functions (`product.crm.contacts`, specifically `get_contact()`) -- never
   `product.crm.models` directly, and never any other product module's
   internals. `product.crm` may NEVER import `product.reputation` -- the
   dependency is one-directional only, matching the actual data-flow
   direction (CRM is the upstream system of record; Reputation is a
   downstream consumer, read-only).
2. `product.reputation`'s use is read-only: `get_contact(actor_user_id,
   tenant_id, contact_id)` resolves the target contact (and its email
   address) before a review request send is attempted. `get_contact()` is
   already RBAC-gated on `crm.contact:read` -- this is a deliberate,
   additional authorization layer, not a bypass: an actor creating a review
   request must independently hold both `reputation.review_request:create`
   (this module's own resource) and `crm.contact:read` (the read this
   module wraps), mirroring exactly the "every registered tool wraps
   exactly one bounded, already-RBAC-gated read" shape `docs/ADR/0006-...`
   already establishes for `product.ai`.
3. `product.reputation` remains fully independent from every other product
   module (`agency`, `marketing`, `conversations`, `telephony`, `ai`,
   `appointments`, `automation`, `websites`, `billing`, `accounting`,
   `reporting`, `white_label`, `templates`, `integrations`) -- this
   exception is narrow and specific to CRM, not a general loosening of
   §2.2's rule, and not a license for Reputation to depend on Automation or
   any other module. In particular, `product.automation` continuing to
   depend only on CRM (not on Reputation) is unaffected by this decision --
   see "Deferred: Automation Integration" below.
4. Enforced with import-linter, not only documentation (`pyproject.toml`):
   - `"product.reputation"` is removed from the "Product modules do not
     depend on each other directly" independence contract's `modules` list
     -- it now has its own, more precise rule instead of the blanket one,
     mirroring exactly how Phase 6/7/9/10/11 removed
     `product.marketing`/`product.appointments`/`product.ai`/
     `product.automation`/`product.websites` for their own single-module
     edges.
   - A new `forbidden`-type contract, "Reputation does not depend on any
     product module except CRM" (`source_modules =
     ["product.reputation"]`, `forbidden_modules` = every product module
     except `product.crm`).
   - A new `layers`-type contract, "Reputation may depend on CRM, never CRM
     on Reputation" (`layers = ["product.reputation", "product.crm"]`).
   - Every other module's own `forbidden_modules` list already names
     `product.reputation` (added defensively when each of those contracts
     was first written, per each module's own comment) -- this ADR does
     not change any of them; Reputation remains something no other module
     may depend on.

## Deferred: Automation Integration

`docs/ROADMAP.md` Phase 12.1's Dependencies line also names "Phase 10
(automation trigger integration)," and Phase 12.3 says the review-received
trigger "extends Phase 10's trigger library." This ADR does **not** grant
any `product.automation <-> product.reputation` edge, in either direction:

- Automation invoking a Reputation action (e.g. "send review request" as a
  workflow step) would need `docs/ROADMAP.md` Phase 10.3A's generic
  action-registry boundary -- Reputation registering an implementation
  against Automation's own protocol, Automation never importing
  Reputation. That registry boundary itself is a separate, substantial
  subphase (Phase 10.3A is its own roadmap entry, recorded as its own ADR
  "when the subphase is actually scheduled" per its own roadmap text, and
  not yet scheduled against Reputation), so wiring Reputation into it now
  would be speculative infrastructure this phase's own scope discipline
  (docs/ROADMAP.md Phase 12's brief: "establish... domain foundation," not
  the full future platform) argues against.
- Automation recognizing a `reputation.review.received` event as a new
  trigger type would require extending `product/automation/`'s own
  closed trigger vocabulary -- a change to Automation's own files, not
  Reputation's, and one this phase does not make.

Phase 12 instead publishes well-shaped, versioned events
(`reputation.review_request.created/.sent/.failed`,
`reputation.review.received`, `reputation.review.responded`) via the
existing `product.foundation.events` dispatcher now, so that a later,
explicitly-scheduled subphase can wire Automation's consumption side
without any change to Reputation's own event-publishing code. This mirrors
`docs/ROADMAP.md` Phase 4.2's own precedent exactly: `crm.opportunity
.stage_changed` was published in Phase 4.2 with "Automation (Phase 10)...
the eventual subscriber, not built yet" stated explicitly as the intended
sequencing.

## Non-Vacuousness Proof (performed, not assumed)

Verified for real against the actual repository at implementation time:

1. A real `product.crm -> product.reputation` import (a throwaway `import
   product.reputation` line added to `product/crm/errors.py`) --
   `lint-imports` reported the new layers contract **broken**. Reverted.
2. A real `product.reputation -> product.agency` import (a throwaway
   `import product.agency` line added to `product/reputation/errors.py`)
   -- `lint-imports` reported the new forbidden contract **broken**.
   Reverted.
3. `product.reputation.review_requests -> product.crm.contacts.get_contact`
   (the real, shipped import) -- `lint-imports` reports this **kept** by
   the new layers contract, as intended.
4. Full-repository `lint-imports` run after this change: every
   pre-existing contract remains **kept**, plus the two new ones -- no
   regression to any other module's own isolation.

(Exact command transcripts are reproduced in this phase's own
implementation/audit report, not duplicated here.)

## Rejected Alternative

A Reputation-owned "reviewer"/"customer" projection, populated by
subscribing to `crm.contact.created`/`crm.contact.updated`. Rejected for
the identical reason `docs/ADR/0005-...`'s own Rejected Alternative section
already gives: this is materially more infrastructure than Phase 12 asks
for (a second copy of contact data to keep synchronized, staleness
questions a live read does not have), built on spec rather than on
demonstrated need.

## Consequences

- `product/reputation/review_requests.py` is the one place in this product
  that imports across the `reputation -> crm` boundary -- every other
  cross-module need in Reputation goes through the event dispatcher
  (permission provisioning via `agency.role_provisioned`,
  `product/reputation/event_handlers.py`) or stays entirely within
  `product/reputation/`, unchanged.
- A future contributor adding a second `product.reputation -> product.crm`
  call site should do so through this same narrow module or an equally
  narrow, clearly-named one -- not mechanically enforced, a code-review
  expectation this ADR records, mirroring every prior CRM-dependency ADR's
  identical note.
- If Reputation later needs write access to CRM data, or a second CRM
  function beyond `get_contact()`, that is a materially different, larger
  decision than this one and requires its own review.
