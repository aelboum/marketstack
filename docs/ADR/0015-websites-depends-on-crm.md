# ADR-0015: Websites May Depend on CRM (One-Directional, Lead Capture Only)

Status: ACCEPTED
Date: 2026-09-22

## Context

`docs/ADR/0009-websites-depends-on-white-label.md` already granted
`product.websites` one narrow, one-directional edge (to `product.white_label`,
for branding resolution) and explicitly declined to decide this one at the
same time, verbatim: *"...not a license for Websites to depend on CRM (a
published page never reads CRM data directly; any future funnel/lead-capture
integration, per `docs/ROADMAP.md` Phase 11.2's own dependency on Phase 6.3,
is out of this decision's scope and would need its own review when that
subphase is actually built)."*

`docs/ROADMAP.md` Phase 22 ("Lead Capture & Qualification Loop") is that
subphase. Its own Scope item (a) requires: *"`product/websites/` gains a
minimal form/submission entity reusing the same trusted-source CRM upsert
Marketing already uses — never a second, divergent lead-capture
mechanism."* The function in question,
`product.crm.contacts.create_or_update_contact_from_trusted_source()`, is
already a published, "trusts its caller" entry point
(`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`) consumed
identically by `product.marketing` and `product.appointments`. Websites
needing the same function, for the same category of reason (a public,
anonymous submission that has verified enough about a submitted identity to
trust it as a real contact), is not a new kind of exception — it is the
third downstream module granted the same one-directional edge, for the
identical reason ADR-0005 already names for the second.

## Decision

1. `product.websites` MAY import `product.crm`'s own published service
   functions — in practice, exactly one:
   `product.crm.contacts.create_or_update_contact_from_trusted_source()` —
   never `product.crm.models` directly, and never any other CRM function.
   `product.crm` may NEVER import `product.websites` — the dependency is
   one-directional only, matching every prior CRM edge's own data-flow
   direction (CRM is the upstream system of record; Websites, like
   Marketing/Appointments/AI/Automation/Reputation before it, is a
   downstream consumer).
2. `product.websites` remains fully independent from every other product
   module (`agency`, `marketing`, `conversations`, `telephony`, `ai`,
   `appointments`, `automation`, `reputation`, `billing`, `accounting`,
   `reporting`, `templates`, `integrations`) — this exception is narrow and
   specific to the one lead-capture write, not a general loosening of
   `docs/ARCHITECTURE.md` §2.2's rule, and not a license for Websites to
   read CRM data for any other purpose (a published page still never reads
   CRM data directly to *render* — ADR-0009's own scope stands unchanged).
   `product.websites` keeps its existing, separate edge to
   `product.white_label` (ADR-0009) unaffected.
3. Enforced with import-linter, not only documentation (`pyproject.toml`):
   - The existing `forbidden`-type contract, "Websites does not depend on
     any product module except White-Label," is renamed "Websites does not
     depend on any product module except White-Label or CRM" and
     `"product.crm"` is removed from its `forbidden_modules` list —
     mirrors exactly how ADR-0006 broadened AI's own equivalent contract
     to name three permitted targets instead of one.
   - A new, separate `layers`-type contract, "Websites may depend on CRM,
     never CRM on Websites" (`layers = ["product.websites", "product.crm"]`)
     — kept independent from the existing White-Label layers contract, for
     the identical reason ADR-0006's own three separate layers contracts
     are not folded into one: a shared multi-layer form would additionally
     permit `product.white_label <-> product.crm` through Websites as an
     intermediary, which is not part of this decision.

## Non-Vacuousness Proof (performed, not assumed)

1. `product.websites.leads` imports
   `product.crm.contacts.create_or_update_contact_from_trusted_source`
   (the real, shipped import) — `lint-imports` reports this **kept** by
   the new layers contract.
2. `lint-imports` run against the full repository after this change: 20
   contracts kept, 0 broken (up from 19 after Phase 21's own Agency ->
   Templates edge) — the new contract pair is additive; every other
   module's own continued isolation from `product.websites` (unchanged in
   each of their own `forbidden_modules` lists) remains intact, and
   `product.websites`'s own existing White-Label edge (ADR-0009) is
   unaffected.
3. `product.crm` was not modified to accommodate this decision at all — it
   still appears in the blanket independence contract's own `modules`
   list (unchanged), so it still cannot import `product.websites` or any
   other product module.

## Rejected Alternative

Routing Websites' lead capture through `product.marketing` instead
(`product.websites -> product.marketing -> product.crm`, mirroring Phase
21's own transitive `product.agency -> product.templates -> product.crm`
shape). Rejected: unlike Agency/Templates (where Templates already owns
the relevant capability — applying a snapshot — and Agency merely
triggers it), Marketing's own `submit_form()` is a sibling capability, not
an owner of the shared upsert function; routing through it would add a
real, load-bearing `product.websites -> product.marketing` edge for no
functional benefit, entangle two otherwise-independent capture surfaces
(a website page's own lead form is not a Marketing-managed form), and
contradict the roadmap's own "a minimal form/submission entity" framing
(website's own entity, not a wrapper around Marketing's).

## Consequences

- `product/websites/leads.py` is the one place in this product that
  imports across the `websites -> crm` boundary — every other Websites
  file remains untouched by this decision.
- A future contributor adding a second `product.websites -> product.crm`
  call site should do so through this same narrow module, or an equally
  narrow, clearly-named one — not mechanically enforced, a code-review
  expectation this ADR records, mirroring every prior CRM-edge ADR's
  identical note.
- If Websites later needs to *read* CRM data (e.g. to render a lead's own
  status back on a dashboard-facing page), that is a materially different,
  larger decision than this one (a write-only edge becoming a read edge
  too) and requires its own review.

## Related ADRs

- `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md` — the
  original grant of `create_or_update_contact_from_trusted_source()` to
  two downstream modules; this ADR extends it to a third, for the
  identical reason.
- `docs/ADR/0009-websites-depends-on-white-label.md` — Websites' own first
  cross-module edge, and the decision that explicitly deferred this one.
- `docs/ROADMAP.md` Phase 22 — Lead Capture & Qualification Loop, the
  phase whose own scope requires this edge.
