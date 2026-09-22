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
- Wired by Phase 22 ("Lead Capture & Qualification Loop"): "form
  submitted" -- what this docstring originally deferred, verbatim, is now
  done: `marketing.lead_captured` (a one-line `publish()` call added to
  the already-shipped `product/marketing/forms.py::submit_form()`) and
  `websites.lead_captured` (published by the new
  `product/websites/leads.py::capture_lead()`) are both real trigger
  types now, and Phase 22 also adds one new CRM-writing action,
  `assign_opportunity` (see `product/automation/actions.py`'s own
  docstring), extending the `docs/ADR/0008-...` edge this module already
  had -- no new import-linter edge was needed for either change (event
  subscription is by string, not by import; the new action reuses the
  same already-approved `product.automation -> product.crm` edge).
- Still deferred, with a concrete reason each: "payment received"/
  "invoice overdue" (Phase 15/24 Accounting does not exist yet -- 10.4's
  own stated dependency), "email/SMS received" (Conversations' own
  SMS/WhatsApp inbound path is itself still PARTIAL, no real vendor --
  `product/conversations/sms.py`), "review received" (Phase 12
  Reputation's own automation integration is itself explicitly deferred,
  `docs/ADR/0010-...`'s own "Deferred: Automation Integration" section).

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
