"""Appointments: staff calendars, availability rules, booking,
rescheduling, cancellation (docs/ROADMAP.md Phase 7.1-7.2).

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

Phase 7.3 (reminders) and 7.4 (calendar provider sync) are **not built in
this pass** -- a separate follow-up wave covers those. `product/appointments/`
here covers 7.1/7.2 only: calendars, availability, booking, reschedule,
cancel.
"""
