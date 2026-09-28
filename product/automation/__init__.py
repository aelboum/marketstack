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
- Wired by Phase 23 ("Customer Lifecycle Loop"): four more Appointments
  lifecycle triggers -- `appointments.appointment.cancelled`/
  `.rescheduled` (one-line `publish()` calls added to all four existing
  cancel/reschedule functions, staff and public alike),
  `.reminder_sent` (added to `send_due_reminders()`), and `.completed`/
  `.no_show` (published by two brand-new staff mutations this phase
  introduces, `staff_complete_appointment()`/`staff_no_show_appointment()`
  -- no status for either existed before this phase). No new action was
  added for this phase's own scope; the existing `create_task` action
  already works against any of them unmodified, since
  `_extract_trigger_ids()` reads `contact_id` out of the payload
  regardless of which event type carried it.
- Wired by Phase 25 completion remediation ("Revenue & Money Workflow"):
  "payment received" -- what this docstring originally deferred pending
  Accounting's own existence -- is now partly done:
  `accounting.invoice.posted` (one of the two flagship events
  `docs/ADR/0014-mini-accounting-foundation.md` Decision 10 and
  `docs/ROADMAP.md`'s own Phase 25 Cross-domain integration section name
  explicitly) is a real trigger type now, published by
  `product/accounting/invoices.py::post_invoice()`. No new action was
  added; `post_invoice()`'s own event payload already carries
  `contact_id` alongside `invoice_id`, so the existing `create_task`/
  `send_email`/`send_webhook` actions already work against it completely
  unmodified, the identical "no new action was added" precedent Phase
  23's own four Appointments triggers above establish. `accounting.bill
  .posted`/`accounting.payment.created`/`accounting.payment.allocated`
  are real, published events too (`docs/ADR/0014-...` Decision 10) but
  are not wired as trigger types here -- one real consumer for one real
  event satisfies Phase 25's own Definition of Done; wiring the rest
  without a stated business need would be exactly the "speculative"
  scope that same Decision warns against.
- Still deferred, with a concrete reason each: "invoice overdue" (a
  derived query condition -- `Invoice.status == 'posted' AND
  outstanding_amount > 0 AND due_date < now`,
  `product/accounting/invoices.py::list_invoices(overdue_only=True)` --
  never itself a published event, so there is nothing to wire a trigger
  to; becoming overdue is not a discrete moment a `publish()` call could
  even mark), "email/SMS received" (Conversations' own SMS/WhatsApp
  inbound path is itself still PARTIAL, no real vendor --
  `product/conversations/sms.py`), "review received" (Phase 12
  Reputation's own automation integration is itself explicitly deferred,
  `docs/ADR/0010-...`'s own "Deferred: Automation Integration" section --
  unaffected by Phase 23, which wires Appointments directly into
  Reputation, not through Automation).

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
