# ADR-0018: Inbound Phone Callers Are Unauthenticated — Contact Trust Boundary

Status: ACCEPTED
Date: 2026-09-29

## Context

The Phase 27.2 ("Call-Initiated Action Safety") readiness audit identified a
blocking architectural gap: `docs/ROADMAP.md`'s own Phase 27.2 scope text
names appointment booking as "the narrowly-required appointment-booking
capability confirmed necessary by the Phase 27 audit," treating the absence
of "phone-based contact lookup/dedup" as a technical gap to close, not as an
open trust-boundary decision. A dedicated caller/contact trust architecture
investigation (this ADR's own predecessor analysis) established that this
framing is incomplete: closing that gap safely requires a decision this
repository has not yet made, and reusing the existing anonymous-contact
machinery unmodified would be unsafe.

**Inbound phone callers are unauthenticated.** `product/telephony/calls.py`'s
own module docstring already states that an inbound provider webhook's
`to_number` — never any caller-supplied value — is the only signal used to
resolve `tenant_id`, and that `Call.contact_id` is never populated for
inbound calls today. Phase 27.1's own roadmap text (`docs/ROADMAP.md`,
Phase 27.1's "Architectural constraints") already states the adjacent
principle for the *AI actor*: "caller identity is not the AI actor identity;
caller ID is not authentication." This ADR extends that same principle to
the *CRM contact* the caller might be talking about, which Phase 27.1 itself
never addressed (27.1's own scope is the call/session/turn/actor foundation,
not business-data attachment).

**Caller ID ("ANI"/`from_number`) is not authentication.** It is a
carrier-supplied signal, trivially misrepresentable ("spoofable") by
construction, and this repository has no code path anywhere that treats it
as proof of identity. Nothing in `product/telephony/` claims otherwise.

**No phone verification mechanism exists.** A repository-wide search (this
ADR's own predecessor investigation) for OTP, SMS/voice verification, magic
links, or any phone-ownership-proof primitive found none. The only
"verification" concepts that exist — `TelephonyProvider.verify_webhook_signature()`
(proves the telephony *provider* sent the event, says nothing about the
human caller) and Login V2/ZITADEL MFA/OTP/WebAuthn (`docs/ADR/0016-...`,
`docs/LOGIN-V2-VERIFICATION.md` — an authenticated human in a browser
session) — are both structurally unreachable from, and irrelevant to, a live
inbound voice call.

**The existing trusted-source contact path is unsafe for this caller.**
`product/crm/contacts.py::create_or_update_contact_from_trusted_source()`
(sanctioned by `docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`
for exactly three named callers — `product/marketing/forms.py::submit_form()`,
`product/appointments/booking.py::book_appointment()`'s existing public
path, `product/websites/leads.py::capture_lead()`) finds an existing contact
by **exact email match** and, on a match, **overwrites** that contact's
`first_name`/`last_name`/`phone` with the caller-supplied values, audited as
`ActorType.SYSTEM`. The function's own docstring is explicit that this is
"never a fourth [caller] without its own ADR." A phone call is a structurally
new, fourth caller. Reusing this function unmodified for a phone-originated
claim would let anyone who knows or guesses an existing customer's email
silently alter that customer's on-file identity fields, with the audit trail
attributing the change to "trusted source" rather than to an unauthenticated
external party. This is unacceptable.

**Booking currently couples contact resolution and appointment creation.**
`product/appointments/booking.py::book_appointment()` requires
`contact_email`/`contact_first_name`/`contact_last_name` as non-optional
parameters and always calls the trusted-source function above — even though
`Appointment.contact_id` is nullable at the schema level, the one existing
booking entry point offers no contact-less path. This is a fact this ADR
must account for, not a defect this ADR fixes.

`product/appointments/models.py::BookingLink` (a public, per-calendar token
resolving `(tenant_id, calendar_id)` before any tenant context exists) is a
**resource-discovery** mechanism — which calendar to book against — never a
caller-identity mechanism. It is named here only to foreclose it being
mistaken for one.

## Decision

**An unauthenticated phone caller must never cause an existing CRM contact
to be matched and updated merely from caller-supplied identity attributes.**

Concretely:

1. **Existing-contact matching by caller-supplied email/phone/name is
   prohibited from a phone-originated flow.** A phone-originated flow MUST
   NOT call `create_or_update_contact_from_trusted_source()` in a way that
   could resolve to an *existing* contact. The specific sequence
   `caller states an existing customer's email → that contact is matched →
   first_name/last_name/phone are overwritten` is explicitly forbidden,
   regardless of how plausible or specific the caller-supplied information
   is.
2. **Anonymous, phone-originated contact creation is deferred, not
   authorized by this ADR.** This ADR does not authorize implementing it
   now. If a future phase creates a new contact from a phone call, it MUST
   satisfy all of the following, or the existing CRM contact model does not
   yet support it safely and a separate CRM model decision is required
   first:
   - it can never match-and-update an existing contact (create-only,
     never find-or-update, for this specific caller category);
   - it cannot attach itself to an existing customer identity merely
     because a supplied email or phone happens to match one on file;
   - it is explicitly, structurally labeled as phone-originated/unverified
     (e.g. a distinct `source` value such as `"voice_call:unverified"`,
     analogous to the existing `source` metadata
     `create_or_update_contact_from_trusted_source()` already records) —
     never indistinguishable from a verified or staff-entered contact;
   - it is never treated as proof of identity for any other purpose;
   - it is never silently merged into an existing contact by any
     background or later process without a separately approved mechanism;
   - reconciling it with a real, pre-existing customer record later
     requires a separate, explicitly approved identity-verification/merge
     mechanism — not invented, designed, or implemented by this ADR.
3. **Read-only appointment availability is explicitly permitted**, because
   it does not create, read, or modify any customer identity — it answers
   "what times are open on this calendar," resolved entirely from the
   trusted inbound DID → tenant mapping (never caller input), gated by the
   receptionist actor's own ordinary RBAC (`CALENDAR_RESOURCE`/`read`) and
   Data Authorization, exactly as every other Phase 26 tool already works.
4. **Contact-bound appointment booking is blocked.** Booking through the
   existing `book_appointment()` path is blocked for phone-originated calls
   for as long as that path performs trusted-source contact resolution as
   its only contact-attachment mechanism, because doing so would require
   either (a) the prohibited existing-contact-match behavior in point 1, or
   (b) the not-yet-authorized anonymous-contact-creation behavior in point
   2 combined with a booking entry point that does not yet exist. Booking
   may become allowed later only once one of the following is separately,
   explicitly approved: a booking path that accepts a phone-originated,
   unverified contact created per point 2's constraints and records the
   appointment as attached to an explicitly unverified identity; or a real
   caller-identity-verification mechanism (not designed here) that
   establishes sufficient identity before any contact attachment.
5. **Caller-provided identity attributes are claims, not credentials.**
   None of the following may ever be treated as authentication, alone or
   in combination, for the purpose of matching, creating, or modifying a
   CRM contact, or for authorizing a business action against one:
   - caller ID / ANI / `from_number`;
   - a caller-supplied email address;
   - a caller-supplied name;
   - a caller-supplied phone number;
   - a `BookingLink` token (resource discovery only — see Context);
   - a caller-supplied appointment ID;
   - a caller's apparent knowledge of existing customer information (a
     correct-sounding detail is not proof of ownership — it may be
     guessed, overheard, phished, or transcribed from a previous,
     unrelated interaction).
6. **Disposition table for caller-supplied identity information**, given
   the decision above:

   | Caller provides | Existing-contact match? | Contact write? | Safe disposition |
   |---|---|---|---|
   | Email matching exactly one existing contact | Never performed by a phone flow | Never | Treat as an unverified claim; do not attach, do not update; may only inform a bounded, non-committal spoken response (e.g. offering to have a human follow up) |
   | Email matching multiple/ambiguous records | N/A (matching itself is prohibited) | Never | Same as above — ambiguity is irrelevant because matching never happens |
   | No email given | N/A | Never | Unaffected — no identity claim to (not) act on |
   | A phone number (their own or another's) | Never used as a lookup key for attachment | Never | `contacts.phone` has no uniqueness constraint and possession of a number is never ownership proof; not usable to resolve a contact for attachment purposes |
   | Another person's information | Never performed | Never | Identical treatment to any other caller-supplied claim — this ADR draws no distinction between "plausible" and "suspicious" claims, since neither is verifiable over this channel |

7. **This decision applies only to the phone/voice channel.** It does not
   revisit or weaken `docs/ADR/0005-...`'s existing sanction of
   `create_or_update_contact_from_trusted_source()` for
   `product/marketing/forms.py`, `product/websites/leads.py`, or
   `book_appointment()`'s existing **public web** booking path — those
   remain unchanged, sighted (typed) interactions with their own
   already-accepted trust posture. This ADR does not reopen that decision;
   it declines to extend it to a fourth, voice-originated caller.
8. **Clarification: tenant-scoped correlation is not the attachment this
   ADR prohibits — and is explicitly permitted, on the terms below.**
   Point 1's prohibition and the Disposition table's phone-number row
   (point 6) are both about *attachment*: treating a caller-supplied
   identifier as sufficient to resolve *which real customer* is on the
   line, for the purpose of overwriting trusted fields, authorizing an
   action, or otherwise claiming the sender's identity. That is not the
   only thing a phone number can be used for, and this ADR was silent —
   not permissive by omission — on the narrower case below. This point
   closes that silence explicitly, so a future implementer does not have
   to (and must not) re-derive it under time pressure.

   - **Correlation is not authentication.** A future inbound-messaging
     workflow (SMS, WhatsApp, or a future voice-transcript-adjacent flow)
     may use the observed sender identifier as a **tenant-scoped
     correlation key** purely to recognize "this inbound message is from
     the same observed sender identifier as a prior one already
     associated with a record in this tenant." A match establishes
     exactly that and nothing more — it does **not** establish that the
     sender is the person the associated contact record represents. This
     is a categorically different claim from identity verification,
     authentication, or ownership proof, and must never be described,
     logged, or coded as any of those things.
   - **The lookup is tenant-scoped and never crosses tenant boundaries.**
     Correlation is always performed as `(tenant_id, normalized
     identifier)` — tenant_id supplied by the same trusted, non-caller
     channel context this ADR's Context section already requires
     (e.g. the inbound DID → tenant mapping), never inferred from the
     identifier itself. The same identifier observed in two different
     tenants correlates to two independent records; no global
     phone-identity concept is introduced, and no identifier may resolve
     a record belonging to a different tenant.
   - **An existing correlated record may be reused only for
     continuity, never as ownership proof.** When the identifier
     matches a record already observed in the same tenant, a future
     workflow may reuse it for conversation/thread continuity, message
     association, inbound interaction history, and CRM activity
     continuity. It must not be reused, or presented anywhere, as
     evidence that the current sender is the person that record
     represents, and it grants no attachment right beyond that
     continuity bookkeeping.
   - **A newly-associated record remains unverified.** When no
     correlated record exists, a future workflow may create one, but it
     must remain explicitly, structurally distinguishable as originating
     from an unverified inbound source — the same `source`-tagging
     discipline point 2 already requires for phone-originated creation
     (e.g. a channel-qualified unverified marker such as
     `"sms:unverified"`/`"whatsapp:unverified"`, mirroring point 2's own
     `"voice_call:unverified"` example) — never indistinguishable from a
     verified or staff-entered record. This point does not invent, name,
     or require a specific schema field; it states the semantic
     requirement a future implementation's own design must satisfy.
   - **Correlation never mutates or upgrades trusted information.**
     A correlation match must never cause any existing trusted field on
     the associated record to be overwritten, and must never cause an
     unverified record to be silently reclassified as verified. If the
     correlated record already carries trusted information, correlation
     preserves it unchanged — the same "never overwrite from an
     unauthenticated signal" principle point 1 already establishes for
     the existing trusted-source function, applied here to any future
     correlation mechanism as well.
   - **Correlation has no authorization consequence.** A successful
     correlation match, by itself, never bypasses, satisfies, or
     substitutes for RBAC, tenant isolation, support-access controls,
     authentication, any policy gate, or any sensitive-action
     authorization. It is bookkeeping for conversation continuity, not a
     grant of any kind.
   - **Correlation never implies merge.** A correlation match must never
     cause two contact records to be implicitly merged. Reconciling a
     correlated-but-unverified record with a separate, real customer
     record later requires its own, separately defined and separately
     approved merge workflow and authorization boundary — not invented,
     designed, or implied by this point.
   - **Provenance is retained.** Any future implementation must preserve
     the distinction between the carrier/inbound identifier and verified
     identity data, and must retain source/provenance information
     sufficient to answer, from the existing `core.audit_log` mechanism
     alone (no new audit infrastructure), whether a given record's
     association originated from an unverified inbound correlation —
     mirroring the Consequences section's existing auditability
     requirement.
   - **Channel scope of this clarification.** Point 7 above limits this
     ADR's original Decision to the phone/voice channel. The distinction
     drawn in this point 8 rests on a channel-independent property — an
     inbound sender identifier supplied by a carrier/messaging platform,
     never verified by this repository — and so applies identically to
     any inbound channel presenting that same kind of unverified,
     carrier-supplied phone identifier, which today includes SMS and
     WhatsApp (both correlate on the same underlying phone-number
     identifier shape as voice, and neither has any phone-ownership-proof
     mechanism documented anywhere in this repository, per this ADR's own
     Context). This point does not assert, and no future implementation
     may assume, anything about a WhatsApp- or SMS-specific identity or
     verification mechanism beyond what is documented here: none exists
     today. If a future channel's sender identifier is not a
     carrier-supplied phone number (for example, an authenticated
     platform account identity), this point does not apply to it without
     its own, separate analysis.

## Consequences

- **Availability**: an AI receptionist may answer "what times are
  available" using `product/appointments/availability.py::compute_available_slots()`
  once Phase 27.2 grants the receptionist actor `CALENDAR_RESOURCE`/`read`
  — no architecture blocker.
- **Contact creation**: no phone-originated contact creation exists until a
  future phase implements the point-2 constraints above (or determines the
  current CRM model cannot support them safely, triggering a separate CRM
  model ADR). This ADR authorizes the *shape* such a mechanism must have;
  it does not build it.
- **Existing contact updates**: never occur from a phone call. This is a
  hard prohibition, not a default that can be reasoned around by a future
  implementer under time pressure.
- **Booking**: blocked for phone calls until either the point-2 mechanism
  and a corresponding booking entry point exist, or a real identity
  verification mechanism is separately approved. `book_appointment()`
  itself is unchanged by this ADR.
- **Identity verification**: explicitly deferred. This ADR neither designs
  nor schedules a verification mechanism; it only states that Option
  C-shaped work (verify-then-book) is not a Phase 27.2 deliverable.
- **Auditability**: any future phone-originated contact creation must be
  distinguishable in `core.audit_log` from every existing trusted-source
  caller (its own `source` value), so "was this contact ever
  caller-claimed-but-unverified" remains answerable from the audit trail
  alone, unchanged from the existing `record()` mechanism (no new audit
  infrastructure).
- **Tenant isolation**: unaffected — tenant resolution for any phone
  capability continues to come exclusively from the trusted inbound DID
  (`PhoneNumber.tenant_id`), never from caller-supplied data, matching
  every existing telephony code path.
- **Future work**: (a) a follow-up decision on whether/how to implement
  phone-originated unverified contact creation per point 2; (b) a
  separately scoped identity-verification-mechanism proposal, if the
  product later decides caller-authenticated booking is worth building;
  (c) a `docs/ROADMAP.md` Phase 27.2 scope correction (see below) —
  performed as its own, later, explicitly-scoped task, not by this ADR.

## Explicit non-goals

This ADR does **not**:

- implement phone verification, OTP, SMS/voice verification, or any other
  identity-proofing mechanism;
- modify `product/crm/contacts.py`, `product/crm/models.py`, or any other
  CRM production code;
- modify `product/appointments/` production code, models, or migrations;
- modify `product/telephony/` production code;
- modify `product/ai/` production code;
- implement any part of Phase 27.2;
- modify Phase 27.0 or Phase 27.1;
- modify Phase 26 (`product/ai/invocation.py`, authorization, approvals,
  audit, or tool registry);
- modify SaaS-OS, migrations, dependencies, or frontend code;
- modify `docs/ROADMAP.md` (see below for the correction this ADR implies
  is needed, left for a separate task).

## Roadmap implication (not applied here)

`docs/ROADMAP.md`'s Phase 27.2 scope text currently reads booking as
"confirmed necessary," blocked only by two named technical gaps (`book_appointment()`
lacking its own `require()` call; "no phone-based contact lookup/dedup
exists today"). This ADR supersedes that framing: the second gap is not a
lookup/dedup implementation detail but the trust-boundary decision recorded
above, and closing it safely means Phase 27.2's own scope should be narrowed
to read-only availability plus call/session/turn correlation, idempotency,
and Phase 26 wiring — with contact-attaching booking explicitly marked
deferred, citing this ADR, rather than listed as in-scope work blocked on a
lookup mechanism. This correction is intentionally **not** made in this ADR
task, per its own instructions; it is reported here as the exact change a
subsequent, dedicated roadmap-correction task should make.
