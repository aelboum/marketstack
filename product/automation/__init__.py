"""Automation / workflow builder (docs/ROADMAP.md Phase 10.2 only -- see
`docs/ADR/0007-automation-execution-substrate.md` for why 10.3
multi-step/branching/delayed workflows are explicitly deferred, pending
your review of that ADR's own durable-engine recommendation).

**Trigger catalog actually wired vs. the roadmap's own full list**
(Phase 10.2's Objective names ten trigger types):

- Wired this phase: `crm.opportunity.stage_changed` (already existed,
  Phase 4.2), `crm.contact.created`, `appointments.appointment.booked`,
  `telephony.call.completed` (all three newly added, one-line `publish()`
  calls in their own already-shipped, already-tested functions), and
  `scheduled` (time-based, via `product/automation/scheduled.py`'s own
  on-demand sweep).
- Deferred, with a concrete reason each: "form submitted" (would need a
  new `publish()` call in `product/marketing/forms.py`, out of this
  phase's own narrow scope of "wire the library," not "instrument every
  remaining module"), "payment received"/"invoice overdue" (Phase 15
  Accounting does not exist yet -- 10.4's own stated dependency),
  "email/SMS received" (Conversations' own SMS/WhatsApp inbound path is
  itself still PARTIAL, no real vendor -- `product/conversations/sms.py`),
  "review received" (Phase 12 Reputation does not exist yet).

**Execution is synchronous, in-process, never `infra.jobs`** -- see
`docs/ADR/0007-automation-execution-substrate.md` for the full
architectural reasoning (a genuine SaaS-OS/Product boundary gap: no
sanctioned synchronous path from a `product.foundation.events.subscribe()`
handler into `infra.jobs.enqueue_job()`, which is `async def`-only).

**Fully consumes existing SaaS-OS/Product primitives, duplicates none**:
`product.foundation.events` (trigger delivery, already-built, unmodified),
`core.rbac` (workflow CRUD authorization, and -- via each action's own
underlying CRM function -- execution authorization), `core.audit_log`
(every execution, allow/deny/failure), `product.crm` (the three
CRM-writing actions, `docs/ADR/0008-automation-depends-on-crm.md`),
`core.email` (the `send_email` action). No second job scheduler, event
bus, idempotency framework, tenant-authorization framework, audit
framework, or secrets framework is introduced.

**AI**: Phase 9's `control_plane` tools are not invoked from this phase's
own action library -- no roadmap-listed Phase 10.2 action names AI
invocation (that is 10.4's own scope, itself gated on 10.2/10.3's
mechanism and, per `docs/ROADMAP.md`, not required until then). Nothing
here bypasses `control_plane.orchestration`, adds a second AI control
plane, or lets model output execute an action directly.
"""
