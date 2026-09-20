"""Appointments: staff calendars, availability rules, booking,
rescheduling, cancellation, reminders, calendar provider seam
(docs/ROADMAP.md Phase 7.1-7.4).

**Tenancy**: the client tenant, same as CRM/Conversations/Marketing -- a
client's own staff calendars and bookings are that client's own business
data. An agency reaches a client's appointment data via inherited
`SUBTREE` role, `get_current_actor` + service-layer `core.rbac.can()`,
never `get_tenant_context()` -- see `docs/ADR/0002-...`'s Phase 4
addendum, which applies unchanged here. No new tenancy concept.

**The second product module permitted to depend on CRM**:
`product/appointments/booking.py` imports `product.crm.contacts` (CRM's
own published, "trusts its caller" service function
`create_or_update_contact_from_trusted_source()`) for the identical
reason `product.marketing` already does -- see
`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md` (extended in
this phase from its original Marketing-only scope) for the full decision.
Every other cross-module need (role-permission granting) goes through the
`agency.role_provisioned` event dispatcher, unchanged -- `product.appointments`
never imports `product.agency`, `product.marketing`, `product.conversations`,
or any other product module.

**Double-booking prevention is a database-enforced invariant, not an
application-level check-then-insert** -- see
`product/appointments/models.py`'s own module docstring for the
PostgreSQL `EXCLUDE` constraint mechanics.

**Phase 7.3 (reminders)**: `product/appointments/reminders.py` provides a
real, bounded, per-tenant on-demand sweep (`send_due_reminders()`), exposed
via `POST /v1/appointments/tenants/{tenant_id}/reminders/sweep` --
see that module's own docstring. Automatic, cross-tenant periodic
scheduling of that sweep is **not built in this pass**: SaaS-OS currently
exposes neither a deferred/scheduled job primitive
(`infra.jobs.enqueue_job()` does not thread arq's own `_defer_until`/
`_defer_by` through) nor a tenant-enumeration function runtime code could
use to sweep across tenants under RLS -- both genuine SaaS-OS capability
gaps, not something this module fakes. Periodically triggering the
per-tenant endpoint across tenants is an operational/deployment concern
outside this product's own code.

**Phase 7.4 (calendar provider sync)**: `product/appointments/calendar_sync.py`
provides the provider-neutral interface (`CalendarProvider` protocol) and
one real in-memory `FakeCalendarProvider` implementation, mirroring
`core.email.provider.EmailProvider`/`FakeEmailProvider`'s exact shape.
Real external provider integration (Google Calendar OAuth, Microsoft
Calendar OAuth, or any other vendor) is **not built in this pass** -- no
vendor is selected, no real HTTP call is made, and this interface is not
wired into `product/appointments/booking.py`'s real booking flow yet;
that remains a separate follow-up wave once a vendor is chosen.
"""
