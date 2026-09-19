"""Forms and public lead capture (docs/ROADMAP.md Phase 6.3).

**`field_definitions` shape** -- a small, fixed, explicit JSON list, never
an open-ended validation engine:

    [{"name": "email", "field_type": "email", "required": true}, ...]

`field_type` is one of `product.marketing.models.VALID_FORM_FIELD_TYPES`
(`"text"`/`"email"`/`"phone"`). Unknown fields submitted beyond what a
form defines are rejected, not silently stored.

**This module owns the one deliberately-unauthenticated write path in
this entire product** (`submit_form()`) -- treat every line here with
that weight. `resolve_form_by_token()` mirrors
`product/white_label/domains.py::resolve_tenant_for_domain()` exactly: a
plain, untenanted `infra.db.session_scope()` read, because there is no
tenant context to scope to until this very lookup resolves one
(`marketing.forms` carries no RLS -- see migration
`0020_marketing_forms`'s own docstring). `submit_form()` performs no
`product.marketing.permissions.require()` call at all, the identical
"trusts its caller" reasoning `product/crm/contacts.py
::create_or_update_contact_from_trusted_source()` documents for its own
half of this same flow -- there is no authenticated actor for a public
form submission to check permission against.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, session_scope, tenant_session_scope

from product.crm.contacts import create_or_update_contact_from_trusted_source
from product.marketing.errors import (
    MarketingFormTokenInvalidError,
    MarketingReferenceNotFoundError,
    MarketingValidationError,
)
from product.marketing.models import (
    MAX_FORM_FIELD_VALUE_LENGTH,
    MAX_FORM_NAME_LENGTH,
    VALID_FORM_FIELD_TYPES,
    MarketingForm,
    MarketingFormSubmission,
)
from product.marketing.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.marketing.permissions import FORM_RESOURCE, require

_FORM_TOKEN_BYTES = 32  # mirrors core/identity/service.py's own invitation-token byte length


@dataclass(frozen=True, slots=True)
class FormFieldDefinition:
    name: str
    field_type: str
    required: bool


@dataclass(frozen=True, slots=True)
class FormView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    form_token: str
    field_definitions: tuple[FormFieldDefinition, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FormSubmissionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    form_id: uuid.UUID
    contact_id: uuid.UUID | None
    submitted_data: dict[str, str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FormSubmissionResult:
    submission_id: uuid.UUID
    contact_id: uuid.UUID | None


def _parse_field_definitions(raw: str) -> tuple[FormFieldDefinition, ...]:
    data = json.loads(raw) if raw else []
    return tuple(
        FormFieldDefinition(
            name=str(item["name"]),
            field_type=str(item["field_type"]),
            required=bool(item.get("required", False)),
        )
        for item in data
    )


def _serialize_field_definitions(fields: list[FormFieldDefinition]) -> str:
    return json.dumps(
        [{"name": f.name, "field_type": f.field_type, "required": f.required} for f in fields]
    )


def _validate_field_definitions(fields: list[FormFieldDefinition]) -> None:
    if not fields:
        raise MarketingValidationError("a form must define at least one field.")
    names_seen: set[str] = set()
    for field in fields:
        if field.field_type not in VALID_FORM_FIELD_TYPES:
            raise MarketingValidationError(
                f"field_type must be one of {VALID_FORM_FIELD_TYPES}, got: {field.field_type!r}"
            )
        if not field.name:
            raise MarketingValidationError("a form field must have a non-empty name.")
        if field.name in names_seen:
            raise MarketingValidationError(f"duplicate field name: {field.name!r}")
        names_seen.add(field.name)


def _to_view(row: MarketingForm) -> FormView:
    return FormView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        form_token=row.form_token,
        field_definitions=_parse_field_definitions(row.field_definitions),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _submission_to_view(row: MarketingFormSubmission) -> FormSubmissionView:
    return FormSubmissionView(
        id=row.id,
        tenant_id=row.tenant_id,
        form_id=row.form_id,
        contact_id=row.contact_id,
        submitted_data=json.loads(row.submitted_data),
        created_at=row.created_at,
    )


# --- Authenticated management -----------------------------------------------


def create_form(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    fields: list[FormFieldDefinition],
) -> FormView:
    require(actor_user_id, tenant_id, resource=FORM_RESOURCE, action="create")
    _validate_field_definitions(fields)
    if len(name) > MAX_FORM_NAME_LENGTH:
        raise MarketingValidationError(f"name exceeds {MAX_FORM_NAME_LENGTH} characters.")
    form_token = secrets.token_urlsafe(_FORM_TOKEN_BYTES)
    with tenant_session_scope(tenant_id) as session:
        row = MarketingForm(
            tenant_id=tenant_id,
            name=name,
            form_token=form_token,
            field_definitions=_serialize_field_definitions(fields),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.form.create",
        resource_type="marketing.form",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_form(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, form_id: uuid.UUID) -> FormView:
    require(actor_user_id, tenant_id, resource=FORM_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingForm, form_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("form", form_id)
        session.expunge(row)
    return _to_view(row)


def list_forms(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[FormView]:
    require(actor_user_id, tenant_id, resource=FORM_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(MarketingForm)
                .where(MarketingForm.tenant_id == tenant_id)
                .order_by(MarketingForm.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def delete_form(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, form_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=FORM_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(MarketingForm, form_id)
        if row is None or row.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("form", form_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="marketing.form.delete",
        resource_type="marketing.form",
        resource_id=str(form_id),
        outcome=AuditOutcome.SUCCESS,
    )


def list_form_submissions(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    form_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[FormSubmissionView]:
    require(actor_user_id, tenant_id, resource=FORM_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        form = session.get(MarketingForm, form_id)
        if form is None or form.tenant_id != tenant_id:
            raise MarketingReferenceNotFoundError("form", form_id)
        rows = (
            session.execute(
                select(MarketingFormSubmission)
                .where(
                    MarketingFormSubmission.tenant_id == tenant_id,
                    MarketingFormSubmission.form_id == form_id,
                )
                .order_by(MarketingFormSubmission.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_submission_to_view(row) for row in rows]


# --- Public, unauthenticated submission --------------------------------------


def resolve_form_by_token(form_token: str) -> FormView | None:
    """Exact-match lookup of `form_token` against `marketing.forms`.
    Returns `None` for an unmapped/malformed token -- never a guess,
    never a default form. Plain, untenanted `session_scope()` read,
    mirroring `product.white_label.domains.resolve_tenant_for_domain()`
    exactly."""
    if not form_token:
        return None
    with session_scope() as session:
        row = (
            session.execute(select(MarketingForm).where(MarketingForm.form_token == form_token))
            .scalars()
            .one_or_none()
        )
        if row is None:
            return None
        session.expunge(row)
    return _to_view(row)


def submit_form(form_token: str, submitted_fields: dict[str, str]) -> FormSubmissionResult:
    """The public entrypoint (`product/marketing/routes.py`'s
    unauthenticated `POST /v1/marketing/forms/{form_token}/submit`).
    Performs no `permissions.require()` call -- see module docstring.

    Validates `submitted_fields` against the form's own
    `field_definitions`: every `required` field must be present and
    non-empty; every submitted field must be bounded
    (`MAX_FORM_FIELD_VALUE_LENGTH`); an unknown field name (not declared
    by the form) is rejected, never silently stored.

    If an `"email"`-typed field was submitted, calls
    `product.crm.contacts.create_or_update_contact_from_trusted_source()`
    to find-or-create the CRM contact. A form with no email field (or one
    left blank despite not being marked required) still records the
    submission, with `contact_id=None` -- never blocked."""
    form = resolve_form_by_token(form_token)
    if form is None:
        raise MarketingFormTokenInvalidError(f"unknown form token: {form_token!r}")

    known_field_names = {f.name for f in form.field_definitions}
    unknown = set(submitted_fields) - known_field_names
    if unknown:
        raise MarketingValidationError(f"unknown field(s) submitted: {sorted(unknown)}")

    for field in form.field_definitions:
        value = submitted_fields.get(field.name, "")
        if field.required and not value:
            raise MarketingValidationError(f"field {field.name!r} is required.")
        if len(value) > MAX_FORM_FIELD_VALUE_LENGTH:
            raise MarketingValidationError(
                f"field {field.name!r} exceeds {MAX_FORM_FIELD_VALUE_LENGTH} characters."
            )

    email_field = next((f for f in form.field_definitions if f.field_type == "email"), None)
    contact_id: uuid.UUID | None = None
    email_value = submitted_fields.get(email_field.name) if email_field else None
    if email_value:
        phone_field = next((f for f in form.field_definitions if f.field_type == "phone"), None)
        name_parts = submitted_fields.get("name", "").split(" ", 1)
        first_name = name_parts[0] if name_parts and name_parts[0] else "Unknown"
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        contact = create_or_update_contact_from_trusted_source(
            form.tenant_id,
            email=email_value,
            first_name=first_name,
            last_name=last_name,
            phone=submitted_fields.get(phone_field.name) if phone_field else None,
            source=f"form:{form.id}",
        )
        contact_id = contact.id

    with tenant_session_scope(form.tenant_id) as session:
        row = MarketingFormSubmission(
            tenant_id=form.tenant_id,
            form_id=form.id,
            contact_id=contact_id,
            submitted_data=json.dumps(submitted_fields),
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        submission_id = row.id
        session.expunge(row)

    record(
        tenant_id=form.tenant_id,
        actor_type=ActorType.SYSTEM,
        action="marketing.form.submitted",
        resource_type="marketing.form_submission",
        resource_id=str(submission_id),
        outcome=AuditOutcome.SUCCESS,
        # Identifiers only -- never the raw submitted_data (name/email/
        # phone/etc.), per docs/ROADMAP.md Phase 6's own PII/audit
        # requirement.
        metadata={"form_id": str(form.id), "contact_id": str(contact_id) if contact_id else None},
    )
    return FormSubmissionResult(submission_id=submission_id, contact_id=contact_id)
