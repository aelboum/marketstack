"""Telephony: phone number provisioning, inbound/outbound call tracking,
routing, call history, recording metadata (docs/ROADMAP.md Phase 8.1-8.3).

**Tenancy**: the client tenant, same as CRM/Conversations/Marketing/
Appointments -- an agency reaches a client's telephony data via inherited
`SUBTREE` role, `get_current_actor` + service-layer `core.rbac.can()`,
never `get_tenant_context()` -- see `docs/ADR/0002-...`'s Phase 4
addendum, which applies unchanged here. No new tenancy concept.

**Fully independent from every other product module** -- unlike
`product.marketing`/`product.appointments`, this phase's own design does
not need a `product.crm` dependency: no CRM function exists that resolves
a contact by phone number (`product/crm/contacts.py` exposes create/get-
by-id/list/update/delete/create-or-update, never a phone lookup), so
caller-ID-to-contact matching is a disclosed, deferred capability gap
(`product/telephony/calls.py`'s own module docstring), not something this
module works around by reading `crm.contacts` directly or duplicating
CRM's own contact store. `Call.contact_id` exists, ready to be populated,
the day CRM publishes a phone-lookup function. `product.telephony` stays
in `pyproject.toml`'s ordinary blanket independence contract -- no ADR-0005-style
exception needed or added.

**No real telephony vendor is selected**
(`docs/RISKS-AND-OPEN-QUESTIONS.md` item 6 lists this explicitly as still
open, the identical unresolved-vendor situation `product/conversations
/sms.py`/`product/conversations/whatsapp.py` already document for Phase
5.3/5.4). Mirroring that established precedent exactly:

- `product/telephony/provider.py` builds the `TelephonyProvider` Protocol
  (mirrors `core/email/provider.py::EmailProvider`'s shape) plus
  `FakeTelephonyProvider`, a real, deterministic, in-memory implementation
  -- not a mock, a genuine second Protocol implementation any test can run
  against with no network access, no credentials.
- Every provider-dependent service function (`provision_phone_number()`,
  `initiate_outbound_call()`, `receive_inbound_call_event()`) takes
  `provider` as a required keyword argument with **no default** -- there
  is no real default telephony provider configured, mirroring
  `product/conversations/sms.py::send_sms_message()`'s identical "no
  default provider" design.
- **No HTTP route is mounted for any provider-dependent write path** --
  the identical reasoning `product/conversations/sms.py`'s own module
  docstring already gives for its own missing inbound webhook route: "a
  route that verifies nothing real would be a false sense of completeness,
  worse than no route at all." A route calling a function with no default
  provider could not function in production regardless; mounting one
  would misrepresent a fake-only capability as a working endpoint. This
  matches `saas-os` `core/webhooks`'s own identical precedent for its P1.10
  primitives: "the verification/replay primitives a future receiver would
  use, never the receiver itself... no HTTP route calls it yet." Every
  provider-dependent function here is real, complete, and fully tested at
  the service layer -- exactly what a future real webhook receiver /
  provisioning route would call once a vendor is actually selected.
- `product/telephony/routes.py` mounts **only** the two read paths that do
  not depend on any vendor decision at all (list/get phone numbers, list/get
  calls) -- real, live, tenant-scoped, RBAC-gated routes over whatever data
  exists, however it got there.

**Phone number resolution must work before any tenant context exists**
(an inbound provider webhook's "to" number is the only thing that can
resolve which tenant it belongs to -- never a caller-supplied tenant id,
per this phase's own explicit "do not trust tenant identifiers supplied by
an unverified external request" requirement) -- `PhoneNumber` is
deliberately **NOT RLS-scoped**, mirroring `product/appointments/models.py
::BookingLink`/`product/white_label/models.py::TenantDomain`'s identical
precedent and reasoning exactly (see `product/telephony/models.py`'s own
docstring). Every other `telephony.*` table (`phone_number_routing_targets`,
`calls`, `call_events`, `call_recordings`) is ordinary RLS-scoped, tenant-
owned data, resolved only after `PhoneNumber` lookup has already
established `tenant_id`.

**Object storage** (Phase 8.3, `docs/RESPONSIBILITY-MATRIX.md` "Object/file
storage" row): built as `product/foundation/storage.py` (not previously
needed by any earlier phase, including Phase 2's branding assets, which
ship no upload mechanism at all -- see that module's own docstring), a
thin `Protocol` + Fake, the identical no-real-vendor treatment as
`TelephonyProvider` above. `product/telephony/recordings.py` is its first
consumer. **No route exposes recordings at all** -- Phase 8.3's own
roadmap Checkpoint requires "dedicated security review before recordings
are enabled for any real tenant," so this pass ships the full data model +
service layer (store/get/purge-on-retention-expiry), fully tested, but
deliberately not wired into any live call-completion flow or API surface.

**Phase 8.4 (human handoff) is not built in this pass** -- the roadmap's
own stated dependency is Phase 9 (AI), which does not exist yet
("implemented once Phase 9's AI call-handling exists to hand off *from*");
there is no AI-handled call to hand off from. Deferred, not silently
narrowed -- see `docs/ROADMAP.md` Phase 8.4's own dependency line.
"""
