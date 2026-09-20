# ADR-0005: Marketing and Appointments May Depend on CRM (One-Directional)

Status: ACCEPTED
Date: 2026-09-21 (Marketing); extended 2026-09-20 (Appointments)

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

**Extension (docs/ROADMAP.md Phase 7.2)**: the same underlying need recurs,
unchanged in shape, for `product.appointments`. Public and staff booking both
need a real contact record to attach the appointment to — the roadmap's own
Phase 7.2 objective is explicit that this must reuse CRM's contact
create-or-update path, not stand up a second, parallel anonymous-contact-
creation mechanism (which would fragment a tenant's contact data across two
independently-deduplicated stores, the exact "second copy of contact data to
keep synchronized" problem this ADR's own Rejected Alternative section
already argues against, this time between products rather than inside one).
`product.crm.contacts.create_or_update_contact_from_trusted_source()` — the
same function this ADR already sanctioned `product.marketing` to call for
form submissions — is a direct, structural fit: it already exists, is already
published, already trusted by exactly this shape of caller ("an
unauthenticated public endpoint that has verified enough about a submitted
identity to trust it as a real contact"), and asks for no new CRM surface
area. This is not a new kind of exception; it is the same one-directional
"downstream product may read/write CRM's own published service functions"
shape, granted to a second downstream module for the same category of reason.

## Decision

1. `product.marketing` and `product.appointments` MAY import `product.crm`'s
   own published service functions (e.g. `product.crm.contacts`,
   `product.crm.search`) — never `product.crm.models` directly, and never any
   other product module's internals. `product.crm` may NEVER import
   `product.marketing` or `product.appointments` — the dependency is
   one-directional only, matching the actual data-flow direction (CRM is the
   upstream system of record; Marketing and Appointments are downstream
   consumers).
   - `product.marketing`'s own use is read-oriented (segmentation queries).
   - `product.appointments`'s own use additionally *writes* through CRM's own
     published function (`create_or_update_contact_from_trusted_source()`) —
     this remains within scope: the write happens entirely inside CRM's own
     service layer, behind CRM's own validation: `product.appointments` never
     constructs or mutates a `crm.contacts` row directly, exactly as
     `product.marketing`'s own segmentation reads never touch `crm.*`
     tables directly. "One-directional" describes the *dependency edge*, not
     a read/write restriction on what the published function itself does.
2. `product.marketing` and `product.appointments` each remain fully
   independent from every other product module (`agency`, `conversations`,
   `telephony`, `ai`, `automation`, `reputation`, `websites`, `billing`,
   `accounting`, `reporting`, `white_label`, `templates`, `integrations`, and
   each other) — this exception is narrow and specific to each module's own
   dependency on CRM, not a general loosening of §2.2's rule for every module
   pair, and not a license for Marketing and Appointments to depend on each
   other. Any future module needing a similar exception (e.g. Reporting
   reading CRM/Marketing/Accounting data, which `docs/ARCHITECTURE.md` §2.2
   itself names as an example) requires its own, separately-justified ADR —
   this decision does not pre-authorize it.
3. Enforced with import-linter, not only documentation:
   - `"product.marketing"` and `"product.appointments"` are both removed from
     the existing "Product modules do not depend on each other directly"
     independence contract's `modules` list in `pyproject.toml` — each now has
     its own, more precise rule instead of the blanket one.
   - The existing `forbidden`-type contract (originally "Marketing does not
     depend on any product module except CRM") is broadened to a second
     `source_modules` entry: `source_modules = ["product.marketing",
     "product.appointments"]`, `forbidden_modules` = every product module
     except `product.crm` (both modules were already present in each other's
     `forbidden_modules` list before this change, since `product.marketing`
     never depended on `product.appointments` and vice versa — this
     broadening does not weaken either module's isolation from every module
     that is not CRM, `product.appointments`/`product.marketing` included).
   - A new `layers`-type contract, `"Appointments may depend on CRM, never
     CRM on Appointments"` (`layers = ["product.appointments", "product.crm"]`)
     — a second, independent layers contract alongside the existing Marketing
     one (not folded into one `layers = [["product.marketing",
     "product.appointments"], "product.crm"]` multi-layer form: that shape
     would additionally permit `product.marketing → product.appointments`
     and `product.appointments → product.marketing` inside the same layer,
     which is not part of this decision — two separate two-layer contracts
     express "each depends on CRM" without also implying "and on each
     other"). Verified empirically (see below), not assumed from the
     parameter order alone.

## Non-Vacuousness Proof (performed, not assumed)

**Marketing (original, 2026-09-21)** — all four checks below were run for
real against the actual repository, each violation added, confirmed to fail
the relevant contract, then reverted, leaving the repository clean:

1. A real `product.crm → product.marketing` import (a throwaway `import
   product.marketing` line added to `product/crm/errors.py`) — `lint-imports`
   reported the layers contract **broken**, exactly as intended. Reverted.
2. A real `product.marketing → product.agency` import (a throwaway `import
   product.agency` line added to `product/marketing/errors.py`) —
   `lint-imports` reported the forbidden contract **broken**. Reverted.
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
   code-review discipline for that one file.

**Appointments (this extension, 2026-09-20)** — the equivalent checks, run
for real against the actual repository at this checkpoint, each violation
added, confirmed to fail, then reverted, leaving the repository clean:

5. A real `product.crm → product.appointments` import (a throwaway `import
   product.appointments` line added to `product/crm/errors.py`) —
   `lint-imports` reported the new Appointments layers contract **broken**.
   Reverted.
6. A real `product.appointments → product.marketing` import (a throwaway
   `import product.marketing` line added to `product/appointments/errors.py`)
   — `lint-imports` reported the (broadened) forbidden contract **broken**,
   proving Appointments' isolation from Marketing specifically survived the
   `source_modules` broadening in point 3 above, not just from every other
   module. Reverted.
7. A real `product.appointments → product.agency` import (the same throwaway
   line, `import product.agency`, added to `product/appointments/errors.py`)
   — `lint-imports` reported the forbidden contract **broken**. Reverted.
8. `product.appointments → product.crm.contacts`
   (`product/appointments/booking.py`'s real, shipped
   `create_or_update_contact_from_trusted_source` import) — `lint-imports`
   reports this **kept** by the new Appointments layers contract, as
   intended.

(Full command transcripts for checks 5-8 are reproduced in this phase's own
implementation report, not duplicated here.)

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

**Appointments-specific rejected alternative**: a second, appointments-owned
anonymous-contact record (e.g. `appointments.booking_contacts`), populated
from the public booking form and never reconciled with `crm.contacts`.
Rejected: this is precisely the fragmented-identity outcome CRM exists to
prevent — the same person booking an appointment and later being emailed by
a marketing campaign or tracked as a CRM opportunity would exist as two (or
three) unrelated records with no deduplication, defeating the entire point of
a single system of record the roadmap establishes CRM to be. Reusing the
existing, already-idempotent `create_or_update_contact_from_trusted_source()`
costs nothing new and keeps exactly one contact identity per real person,
regardless of which product surface first captured them.

## Consequences

- `product/marketing/segmentation.py` and `product/appointments/booking.py`
  are the two places in this product that import across the `crm` sibling
  boundary — every other cross-module need in this product still goes
  through the event dispatcher or `product/foundation/`, unchanged.
- A future contributor adding a second `product.marketing → product.crm` or
  `product.appointments → product.crm` call site should do so through the
  existing narrow module (`segmentation.py`/`booking.py`) or an equally
  narrow, clearly-named one, rather than scattering `product.crm` imports
  through either module's other files — not mechanically enforced, a
  code-review expectation this ADR records.
- `product.marketing` and `product.appointments` still may not import each
  other, directly or via any shared helper module — this ADR grants each of
  them their own, independent edge to CRM only, not an edge to each other. A
  future need for the two to interact (e.g. a marketing campaign triggered by
  an appointment event) should go through the `agency.role_provisioned`-style
  event dispatcher, or its own ADR if a live read genuinely turns out to be
  required.
- If Marketing or Appointments later needs broader write access to CRM data
  (beyond the one already-published, already-trusted
  `create_or_update_contact_from_trusted_source()` entry point), that is a
  materially different, larger decision than this one and requires its own
  review.
