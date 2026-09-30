# ADR-0019: Conversations May Depend on CRM (One-Directional, Phone-Keyed Correlation Only)

Status: ACCEPTED
Date: 2026-09-30

## Context

`docs/ROADMAP.md` Phase 30 ("Unified Inbox — phone-keyed identity resolution
+ auto-created threads") requires a narrowly scoped trusted inbound path
that, given a tenant-scoped inbound phone identifier, resolves or creates a
CRM contact and resolves or creates the corresponding conversation thread.
This is infrastructure for future inbound SMS/WhatsApp/call integrations,
not those integrations themselves.

`product.conversations` is currently a member of the blanket independence
contract (`pyproject.toml`'s "Product modules do not depend on each other
directly") — the same starting position `product.marketing`,
`product.appointments`, `product.ai`, `product.automation`,
`product.websites`, `product.reputation`, `product.templates`,
`product.agency`, and `product.accounting` each started from before their
own, separately-justified single-module edges (ADR-0005, ADR-0006,
ADR-0008, ADR-0009/0015, ADR-0010, ADR-0013, Phase 21, ADR-0014/Decision 6
respectively). `product/conversations/threads.py`'s own module docstring
already documents *why* it has never imported `product.crm`: doing so would
violate that same independence contract, so `create_thread()`'s
`contact_id` validation instead relies entirely on the database's own
composite foreign-key constraint.

`docs/ADR/0018-inbound-phone-caller-contact-trust-boundary.md` point 8
already authorizes the shape this edge must take: a future inbound-messaging
workflow (SMS, WhatsApp, or a phone-identifier-adjacent flow) may use the
observed sender identifier as a **tenant-scoped correlation key**, never as
authentication, never mutating a matched record's trusted fields, and
labeling any newly-created record as unverified. Phase 30 is that future
workflow's backend slice. This ADR supplies the one piece ADR-0018 itself
explicitly declined to build: the actual cross-module dependency and the
narrow function pair it authorizes.

## Decision

1. `product.conversations` MAY import `product.crm`'s own published service
   functions — in practice, exactly one new one:
   `product.crm.contacts.create_or_reuse_contact_from_trusted_source_by_phone()`
   — never `product.crm.models` directly, and never any other CRM function.
   `product.crm` may NEVER import `product.conversations` — the dependency
   is one-directional only, matching every prior CRM edge's own data-flow
   direction (CRM is the upstream system of record; Conversations, like
   Marketing/Appointments/AI/Automation/Websites/Reputation/Templates/Agency/
   Accounting before it, is a downstream consumer for this one purpose).
2. `product.conversations` remains fully independent from every other
   product module (`agency`, `marketing`, `telephony`, `ai`, `appointments`,
   `automation`, `reputation`, `websites`, `billing`, `accounting`,
   `reporting`, `white_label`, `templates`, `integrations`, `platform`) —
   this exception is narrow and specific to the one phone-correlation call,
   not a general loosening of `docs/ARCHITECTURE.md` §2.2's rule.
   `product.conversations`'s existing authenticated `create_thread()` path
   (and its existing reliance on the database FK, not a CRM import, for
   `contact_id` validation) is unchanged.
3. The new CRM function is a distinct function from the existing
   `create_or_update_contact_from_trusted_source()` (ADR-0005/0015),
   never a shared call site — see that function's own docstring and
   `product/crm/contacts.py` for why: ADR-0018 point 8 requires the
   phone-correlation path to never mutate a matched contact's trusted
   fields on a match, which is a materially different contract from the
   email-keyed function's existing update-on-match behavior.
4. Enforced with import-linter, not only documentation (`pyproject.toml`):
   - `product.conversations` is removed from the blanket independence
     contract's `modules` list.
   - A new `forbidden`-type contract, "Conversations does not depend on any
     product module except CRM," mirrors every prior single-edge module's
     own contract shape exactly.
   - A new, separate `layers`-type contract, "Conversations may depend on
     CRM, never CRM on Conversations" (`layers = ["product.conversations",
     "product.crm"]`).

## Non-Vacuousness Proof (performed, not assumed)

1. `product.conversations.threads` imports
   `product.crm.contacts.create_or_reuse_contact_from_trusted_source_by_phone`
   (the real, shipped import) — `lint-imports` reports this kept by the new
   layers contract.
2. `product.crm` was not modified to accommodate this decision's import
   direction — it still appears in the blanket independence contract's own
   `modules` list (unchanged), so it still cannot import
   `product.conversations` or any other product module.

## Non-goals

This ADR does not authorize:

- phone-based contact **authentication** or identity verification of any
  kind (ADR-0018 governs this unchanged; this ADR grants only the import
  edge and the narrow function it carries, not a reopening of that
  decision);
- mutating an existing, correlation-matched contact's trusted fields from
  an inbound phone identifier (explicitly prohibited by the new function's
  own contract, mirroring ADR-0018 point 8);
- contact merging of any kind;
- any SMS/WhatsApp/telephony provider integration, webhook route, or
  vendor selection;
- a second `product.conversations -> product.crm` call site beyond the one
  this Phase authorizes without its own review, mirroring every prior
  CRM-edge ADR's identical note.

## Consequences

- `product/conversations/threads.py` is the one place in
  `product/conversations/` that imports across the `conversations -> crm`
  boundary for this phase.
- A future contributor adding a second `product.conversations ->
  product.crm` call site should do so through this same narrow function, or
  an equally narrow, clearly-named one — not mechanically enforced, a
  code-review expectation this ADR records, mirroring every prior CRM-edge
  ADR's identical note.

## Related ADRs

- `docs/ADR/0018-inbound-phone-caller-contact-trust-boundary.md` — the
  trust-boundary decision this ADR's function pair implements (point 8
  specifically).
- `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`,
  `docs/ADR/0015-websites-depends-on-crm.md` — the precedent shape this ADR
  follows for the import-linter mechanics; the email-keyed trusted-source
  function those ADRs grant is explicitly NOT reused here (see Decision 3).
