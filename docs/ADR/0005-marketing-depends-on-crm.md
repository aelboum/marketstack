# ADR-0005: Marketing May Depend on CRM (One-Directional)

Status: ACCEPTED
Date: 2026-09-21

## Context

`docs/ROADMAP.md` Phase 6.1's own Objective requires "audience segmentation
query" against CRM data (contacts, tags, custom fields) before a campaign can
send. This is a live, synchronous read at campaign-send time — a caller needs
the actual, current set of contacts matching a tag/custom-field/text filter,
not an eventually-consistent projection built from events. No CRM event for
"contact created" or "contact tagged" exists today (Phase 4 only ever
published `crm.opportunity.stage_changed`, and only because the roadmap
explicitly named that one event), and building a full contact-event stream
plus a marketing-side projection of it now would be new infrastructure the
roadmap does not ask for, to serve a need a direct read already satisfies
correctly.

`docs/ARCHITECTURE.md` §2.2 states the existing rule plainly: "A module never
calls another module's internal service functions or reads another module's
tables directly, even for read-only purposes," offering exactly two sanctioned
paths — promote a genuinely generic capability to `product/foundation/`, or
react to another module's state change via the event dispatcher. Segmentation
fits neither cleanly: it is not a generic, domain-agnostic capability (it is
inherently "query CRM's own contact/tag/custom-field tables"), and it is not
a reaction to a discrete state-change event (a campaign send needs the live,
current membership of a segment, not a stream of past changes to reconstruct
it from). This is the first genuine case in this codebase of one product
module needing to read another product module's own tenant-owned business
data for a real, roadmap-specified purpose — distinct from the agency↔crm
precedent (`docs/ADR/0002-...`), which only ever needed the event dispatcher
for one-way permission-granting, never a live data read.

## Decision

1. `product.marketing` MAY import `product.crm`'s own published,
   read-oriented service functions (e.g. `product.crm.contacts`,
   `product.crm.search`) — never `product.crm.models` directly, and never
   any other product module's internals. `product.crm` may NEVER import
   `product.marketing` — the dependency is one-directional only, matching
   the actual data-flow direction (CRM is the upstream system of record;
   Marketing is a downstream consumer, per the brief's own framing: "Phase 4
   CRM is the existing system of record... Marketing must consume those
   capabilities").
2. `product.marketing` remains fully independent from every other product
   module (`agency`, `conversations`, `telephony`, `ai`, `appointments`,
   `automation`, `reputation`, `websites`, `billing`, `accounting`,
   `reporting`, `white_label`, `templates`, `integrations`) — this exception
   is narrow and specific to CRM, not a general loosening of §2.2's rule for
   every module pair. Any future module needing a similar exception (e.g.
   Reporting reading CRM/Marketing/Accounting data, which `docs/ARCHITECTURE.md`
   §2.2 itself names as an example) requires its own, separately-justified
   ADR — this decision does not pre-authorize it.
3. Enforced with import-linter, not only documentation:
   - `"product.marketing"` is removed from the existing "Product modules do
     not depend on each other directly" independence contract's `modules`
     list in `pyproject.toml` — it now has its own, more precise rule
     instead of the blanket one.
   - A new `forbidden`-type contract, `"Marketing does not depend on any
     product module except CRM"` (`source_modules = ["product.marketing"]`,
     `forbidden_modules` = every product module except `product.crm`),
     mirrors the exact shape of the existing "Foundation does not depend on
     any other product module" contract.
   - A new `layers`-type contract, `"Marketing may depend on CRM, never CRM
     on Marketing"` (`layers = ["product.marketing", "product.crm"]`) —
     import-linter's layers semantics: a higher-listed layer may import a
     lower one, never the reverse. Verified empirically (see below), not
     assumed from the parameter order alone.

## Non-Vacuousness Proof (performed, not assumed)

All four checks below were run for real against the actual repository, each
violation added, confirmed to fail the relevant contract, then reverted,
leaving the repository clean:

1. A real `product.crm → product.marketing` import (a throwaway `import
   product.marketing` line added to `product/crm/errors.py`) — `lint-imports`
   reported the layers contract **broken**, exactly as intended. Reverted.
2. A real `product.marketing → product.agency` import (a throwaway `import
   product.agency` line added to `product/marketing/errors.py`) —
   `lint-imports` reported the new forbidden contract **broken**. Reverted.
3. `product.marketing → product.crm.contacts` (the real, shipped
   `product/marketing/segmentation.py` import) — `lint-imports` reports this
   **kept** by the layers contract, as intended.
4. `product.marketing → product.crm.models` — the layers contract is a
   module-level check (import-linter has no notion of "this module's
   published interface vs. its internals" within a single allowed edge); it
   does not by itself distinguish importing `product.crm.contacts` (the
   intended, published surface) from importing `product.crm.models` (an
   internal, ORM-only module) — both are permitted by the layers contract as
   written. **This is a stated limitation of the mechanism, not an
   oversight**: `product/marketing/segmentation.py`'s own module docstring
   names the specific `product.crm` modules it is allowed to import
   (`product.crm.contacts`, `product.crm.search`), and this remains a
   code-review discipline for that one file, the same way `saas-os` itself
   relies on code review (not a mechanical check) to keep a module from
   reaching past another's published functions into its internals when
   nothing stops it syntactically from doing so within an already-permitted
   import edge.

## Rejected Alternative

An event-sourced/projected copy of segmentable contact data inside
`product/marketing/` (CRM publishes `contact.created`/`contact.tagged`/etc.
events; Marketing subscribes and maintains its own read-optimized projection
to query against). Rejected for now: this is meaningfully more
infrastructure than 6.1 actually asks for (a new event taxonomy inside CRM
that nothing else needs yet, a second copy of contact data to keep
synchronized, staleness/consistency questions a live query does not have),
built on spec rather than on demonstrated need — exactly the
"infrastructure before evidence" pattern `docs/ADR/0002-...`'s own Rejected
Alternative section already argues against for a structurally similar
question. If a second, real need for a marketing-side contact projection
appears later (e.g. a requirement for segmentation to run over so much data
that a live query becomes a real performance problem), revisit this then,
informed by that concrete need rather than a hypothetical one.

## Consequences

- `product/marketing/segmentation.py` is the one place in this product that
  imports across the `crm`/`marketing` sibling boundary — every other
  cross-module need in this product still goes through the event
  dispatcher or `product/foundation/`, unchanged.
- A future contributor adding a second `product.marketing → product.crm`
  call site should do so through `product/marketing/segmentation.py` (or an
  equally narrow, clearly-named module) rather than scattering `product.crm`
  imports through `product/marketing/`'s other files — not mechanically
  enforced, a code-review expectation this ADR records.
- If Marketing later needs write access to CRM data (not just segmentation
  reads), that is a materially different, larger decision than this one and
  requires its own review — this ADR authorizes reads of CRM's published
  service functions only.
