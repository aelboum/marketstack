# Risks and Open Questions

Status: PROPOSED. This is the list of things this planning phase deliberately
did not decide, plus the specific decisions that need your explicit approval
before Phase 1 (`docs/ROADMAP.md`) can begin.

## Decisions Requiring Your Approval Before Phase 1

1. **Approve the roadmap and architecture overall** — `docs/ARCHITECTURE.md`,
   `docs/RESPONSIBILITY-MATRIX.md`, `docs/ROADMAP.md`. This is the primary
   gate (`docs/ROADMAP.md` Phase 0's own checkpoint).
2. **`saas-os` version to pin.** `saas-os` has no tagged release yet (its own
   distribution investigation notes "no released tag/commit exists yet").
   You need to either cut a first tag/commit in `saas-os` to pin against, or
   confirm this product should pin an untagged commit SHA initially.
3. **Repository hosting/location** for this product (GitHub org, visibility,
   access control) — not assumed here.
4. **Repository directory rename.** `docs/ADR/0001-...` establishes that
   `marketstack` is not a binding identifier, but does not rename the
   directory. Confirm whether to rename it now (to a neutral name, e.g.
   `agency-product`) or leave it until a commercial name is chosen.
5. **Workflow durability engine** (`docs/ROADMAP.md` Phase 10.1) — this
   roadmap defers the actual choice to a Phase 10.1 spike/ADR by design (it
   needs the real trigger/action catalog from Phases 4–9 to evaluate
   against), but flag now if you already have a strong preference (e.g.
   Temporal specifically) so the spike isn't starting from zero.
6. **Initial integration providers** for SMS, WhatsApp, telephony, and
   calendar sync (`docs/INTEGRATIONS.md`) — this roadmap deliberately does
   not pick vendors, but you may already have preferences (cost, existing
   relationships, Dutch-market coverage) worth recording before Phase 5/8
   planning starts.
7. **Accountant/legal reviewer** for the Dutch compliance checkpoints
   (`docs/ROADMAP.md` Phase 15.6, 15.7, 18.2) — who this is, and when they
   should be engaged (ideally before Phase 15 starts, not only at its
   checkpoint, so the data model doesn't need rework after the fact).
8. **Frontend code-sharing with `saas-os`.** `docs/ARCHITECTURE.md` §6
   recommends no attempted reuse beyond eyeballing the i18n pattern once —
   confirm this, or flag if a shared design system across future products
   is a near-term goal (which would change this recommendation).

## Architectural Risks (Carried Forward From SaaS-OS's Own Precedent)

Mirroring `saas-os`'s own distribution investigation's risk-disclosure
discipline (`saas-os` `docs/architecture/SAAS-OS-DISTRIBUTION-ARCHITECTURE.md`
§16), stated plainly rather than hidden:

- **Zero real consumers of `saas-os` today besides this product** (and
  whatever the "Dograh" project referenced throughout `saas-os`'s ADRs turns
  out to be — its actual status wasn't in scope for this investigation).
  Every Category-A capability this roadmap relies on is well-tested in
  isolation and in the reference-consumer fixture, but this product will be
  among the first real-world proof that the whole consumption model works
  end-to-end. Expect some friction in Phase 1 that this document couldn't
  fully anticipate.
- **Two-command migration discipline** (`docs/REPOSITORY-STRATEGY.md`) is a
  process risk, not something the architecture prevents outright — mitigated
  by the single bootstrap script in Phase 1.2, but worth remembering as an
  operational habit, not just a one-time setup.
- **`saas-os`'s own major-version support window is undecided** (flagged as
  an open question in `saas-os`'s own distribution investigation, §17
  there). This product has no visibility into how long an old `saas-os`
  major will remain patchable — worth raising with whoever maintains
  `saas-os` before this product goes to production on a specific major
  version.
- **The Category B items in `docs/RESPONSIBILITY-MATRIX.md`** (object
  storage, custom-domain resolution, a generic event bus, a durable
  workflow substrate) are built inside this product as interim solutions.
  If a second product is ever built on `saas-os`, there is real duplicated-
  effort risk if that product reinvents the same things independently
  instead of the two efforts converging on a proposal back to `saas-os`.
  Worth flagging to whoever owns `saas-os`'s own roadmap once this product
  is far enough along to have real, battle-tested interfaces worth
  proposing.
- **Financial-data retention vs. GDPR erasure tension**
  (`docs/ACCOUNTING-SCOPE.md`, `docs/ROADMAP.md` Phase 15.7) is a genuine,
  currently-unresolved legal question this architecture flags but does not
  resolve — resolving it is explicitly gated behind legal review, not
  engineering judgment.
- **AI receptionist blast radius** (`docs/ROADMAP.md` Phase 9.2) — real
  customers interacting with an autonomous voice agent on a live phone
  line is the single highest-consequence capability in this initial
  roadmap. The roadmap gates it behind a dedicated checkpoint, but you
  should decide how conservative the initial confidence/escalation
  threshold should be before Phase 9.2 implementation starts, not after.
- **Snapshot/clone ID-remapping** (`docs/ROADMAP.md` Phase 14.2) is
  named as the second-highest isolation risk in the whole roadmap — a bug
  here is a cross-tenant data leak, not a cosmetic defect. Worth extra
  review time budgeted specifically for this subphase.

## Explicitly Deferred (Should Not Be Solved Now)

Mirroring `saas-os`'s own "avoid premature infrastructure" doctrine, applied
to this product's own planning:

- A private package index for this product's own downstream consumers (this
  product has none yet — it is itself the consumer, not a platform others
  build on).
- A second jurisdiction's accounting rules beyond the Netherlands.
- A generic plugin/module-marketplace system for third parties to extend
  this product — no evidence of need yet.
- Native mobile apps.
- A formal SLA/compliance certification target (SOC 2, ISO 27001, etc.) —
  revisit once real enterprise-agency demand names a specific requirement,
  exactly as `saas-os` `docs/SECURITY.md` §11 defers its own compliance
  target the same way.

## What Happens Next

Per `docs/ROADMAP.md` Phase 0's checkpoint: this repository stays
documentation-only until you approve this document set (or return specific
changes). No code, no dependency installation, no git initialization, and no
commit has been made as part of producing this roadmap.
