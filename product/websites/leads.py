"""Public lead capture from a published page (docs/ROADMAP.md Phase 22,
"Lead Capture & Qualification Loop"). The one file in `product/websites/`
that imports across the `websites -> crm` boundary
(`docs/ADR/0015-websites-depends-on-crm.md`).

**A minimal form/submission entity, never a form-builder** -- unlike
`product/marketing/forms.py`'s own configurable `field_definitions`
model, a website's lead-capture form has one fixed shape (name, email,
optional phone, optional message). This is deliberate: the roadmap asks
for "a minimal form/submission entity," not a second, divergent
form-configuration system alongside Marketing's own.

**Reuses the exact same trusted-source CRM upsert Marketing already
uses** -- `product.crm.contacts.create_or_update_contact_from_trusted_source()`
-- never a second, parallel anonymous-contact-creation path. Called
*outside* (before) the idempotency-wrapped write below: it is itself
naturally idempotent by email within a tenant (module docstring of that
function), and it internally opens its own `tenant_session_scope()`,
which is incompatible with `core.idempotency.run_idempotent()`'s own
"business_fn must use the given session it is given, never open its own"
contract -- so the two cannot be composed into one atomic transaction.
This is disclosed, not hidden: a retried submission may re-run the
contact upsert (harmless -- it is idempotent by construction) even on a
replay that skips the actual `LeadSubmission` insert.

**Idempotency**: the `LeadSubmission` insert (+ audit + event) IS wrapped
in `core.idempotency.run_idempotent()`, keyed by `(tenant_id,
operation="websites.lead_capture", idempotency_key)` -- a caller-supplied
key (mirrors `product/billing/routes.py`'s own established required-body-
field convention, not the optional `Idempotency-Key` header nothing in
`product/` currently uses). A retried request with the same key never
creates a second `LeadSubmission` row, and the audit entry/event below
fire only on the real (non-replay) attempt.

**No authorization, deliberately** -- `capture_lead()` takes no
`actor_user_id` and calls no `product.websites.permissions.require()`,
mirroring `product/marketing/forms.py::submit_form()`'s/
`product/appointments/booking.py::book_appointment()`'s own identical
"the one legitimately anonymous write path" precedent. Reached only via
the public, rate-limited route
(`product/websites/routes.py::public_capture_lead_route()`), never from
any authenticated caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import run_idempotent
from infra.db import select, tenant_session_scope

from product.crm.contacts import create_or_update_contact_from_trusted_source
from product.foundation.events import Event, publish
from product.websites.errors import WebsiteReferenceNotFoundError, WebsiteValidationError
from product.websites.models import (
    MAX_LEAD_EMAIL_LENGTH,
    MAX_LEAD_MESSAGE_LENGTH,
    MAX_LEAD_NAME_LENGTH,
    MAX_LEAD_PHONE_LENGTH,
    STATUS_PUBLISHED,
    LeadSubmission,
    Page,
)
from product.websites.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.websites.permissions import WEBSITE_RESOURCE, require

LEAD_CAPTURED_EVENT_TYPE = "websites.lead_captured"
LEAD_CAPTURED_EVENT_VERSION = 1

_IDEMPOTENCY_OPERATION = "websites.lead_capture"


@dataclass(frozen=True, slots=True)
class LeadSubmissionResult:
    submission_id: uuid.UUID
    is_replay: bool


def _validate(field: str, value: str, *, max_length: int, required: bool) -> str:
    if required and not value.strip():
        raise WebsiteValidationError(f"{field} must not be empty.")
    if len(value) > max_length:
        raise WebsiteValidationError(f"{field} exceeds {max_length} characters.")
    return value


def capture_lead(
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    page_id: uuid.UUID,
    *,
    first_name: str,
    last_name: str,
    email: str,
    phone: str | None,
    message: str | None,
    idempotency_key: str,
) -> LeadSubmissionResult:
    """The public entrypoint. `page_id` must be a real, PUBLISHED page in
    `tenant_id`/`website_id` -- raises `WebsiteReferenceNotFoundError`
    otherwise (mapped to the same non-enumerating 404 as everywhere else
    in this module), never distinguishing "unknown page" from "unpublished
    page" from "wrong website," per this product's standing non-
    enumeration discipline."""
    _validate("first_name", first_name, max_length=MAX_LEAD_NAME_LENGTH, required=True)
    _validate("last_name", last_name, max_length=MAX_LEAD_NAME_LENGTH, required=True)
    _validate("email", email, max_length=MAX_LEAD_EMAIL_LENGTH, required=True)
    if phone is not None:
        _validate("phone", phone, max_length=MAX_LEAD_PHONE_LENGTH, required=False)
    if message is not None:
        _validate("message", message, max_length=MAX_LEAD_MESSAGE_LENGTH, required=False)

    with tenant_session_scope(tenant_id) as session:
        page = session.get(Page, page_id)
        if (
            page is None
            or page.tenant_id != tenant_id
            or page.website_id != website_id
            or page.status != STATUS_PUBLISHED
        ):
            raise WebsiteReferenceNotFoundError("page", page_id)

    # Outside the idempotent-wrapped block below -- see module docstring.
    contact = create_or_update_contact_from_trusted_source(
        tenant_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        source=f"website:{page_id}",
    )

    def _insert_submission(session) -> dict[str, object]:
        submission_id = uuid.uuid4()
        session.add(
            LeadSubmission(
                id=submission_id,
                tenant_id=tenant_id,
                website_id=website_id,
                page_id=page_id,
                contact_id=contact.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                message=message,
            )
        )
        session.flush()
        return {"submission_id": str(submission_id)}

    is_replay, result = run_idempotent(
        tenant_id,
        _IDEMPOTENCY_OPERATION,
        idempotency_key,
        fingerprint_payload={"page_id": str(page_id), "email": email},
        business_fn=_insert_submission,
    )
    submission_id = uuid.UUID(str(result["submission_id"]))

    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action="websites.lead.submitted",
            resource_type="websites.lead_submission",
            resource_id=str(submission_id),
            outcome=AuditOutcome.SUCCESS,
            # Identifiers only -- never the raw name/email/phone/message,
            # per this product's uniform audit-metadata discipline.
            metadata={
                "website_id": str(website_id),
                "page_id": str(page_id),
                "contact_id": str(contact.id),
            },
        )
        publish(
            Event(
                type=LEAD_CAPTURED_EVENT_TYPE,
                version=LEAD_CAPTURED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={
                    "contact_id": str(contact.id),
                    "website_id": str(website_id),
                    "page_id": str(page_id),
                    "submission_id": str(submission_id),
                },
            )
        )

    return LeadSubmissionResult(submission_id=submission_id, is_replay=is_replay)


@dataclass(frozen=True, slots=True)
class LeadSubmissionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    website_id: uuid.UUID
    page_id: uuid.UUID
    contact_id: uuid.UUID | None
    first_name: str
    last_name: str
    email: str
    phone: str | None
    message: str | None
    created_at: datetime


def _to_view(row: LeadSubmission) -> LeadSubmissionView:
    return LeadSubmissionView(
        id=row.id,
        tenant_id=row.tenant_id,
        website_id=row.website_id,
        page_id=row.page_id,
        contact_id=row.contact_id,
        first_name=row.first_name,
        last_name=row.last_name,
        email=row.email,
        phone=row.phone,
        message=row.message,
        created_at=row.created_at,
    )


def list_lead_submissions(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    website_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[LeadSubmissionView]:
    """Staff-facing read -- so a captured lead is actually visible
    somewhere beyond the CRM contact it produced (docs/ROADMAP.md Phase
    22's own "make it usable" business outcome). Gated by the same
    `WEBSITE_RESOURCE` every other Website/Page read uses -- a lead
    submission has no independent access boundary apart from the website
    that owns it, mirrors `product/websites/permissions.py`'s own
    consolidation principle exactly."""
    require(actor_user_id, tenant_id, resource=WEBSITE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(LeadSubmission)
                .where(
                    LeadSubmission.tenant_id == tenant_id,
                    LeadSubmission.website_id == website_id,
                )
                .order_by(LeadSubmission.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


__all__ = [
    "LEAD_CAPTURED_EVENT_TYPE",
    "LeadSubmissionResult",
    "LeadSubmissionView",
    "capture_lead",
    "list_lead_submissions",
]
