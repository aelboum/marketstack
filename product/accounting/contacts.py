"""Customer/supplier role-tagging on existing CRM contacts (ADR-0014
Decision 6, docs/ROADMAP.md Phase 25). `crm.contacts` remains the tenant's
only person/organization identity table -- this module never creates a
duplicate customer/supplier record, and never references `crm.companies`
(Decision 6's own addendum: a company is represented through its own
billing contact, `crm.contacts.company_id`, never a second, parallel
reference here).

`product.accounting` reads `crm.contacts` only through
`product.crm.contacts.get_contact()` -- the identical "reuse the
aggregate's own service layer, never touch its tables directly" rule
`product/templates/snapshots.py` already established for
`product.crm.pipelines`. `get_contact()` itself authorizes the *same*
actor for `crm.contact:read` -- a real, live dependency, not merely a
documented one (every owner/member role already holds it via CRM's own
provisioning).

**Deletion (Decision 6 addendum)**: `accounting.contact_profiles
.contact_id`'s FK carries no `ON DELETE` clause (default `RESTRICT`) --
`product.crm.contacts.delete_contact()` fails with a raw, untranslated
`IntegrityError` once a contact is tagged. `product/crm/` is not modified
here to add a friendlier error -- a disclosed, accepted trade-off, see
the ADR's own addendum for the full reasoning.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.accounting.errors import (
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.models import VALID_CONTACT_ROLES, ContactProfile
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import INVOICE_RESOURCE, require
from product.crm.contacts import get_contact


@dataclass(frozen=True, slots=True)
class ContactProfileView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    role: str
    created_at: datetime


def _to_view(row: ContactProfile) -> ContactProfileView:
    return ContactProfileView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        role=row.role,
        created_at=row.created_at,
    )


def _validate_role(role: str) -> str:
    if role not in VALID_CONTACT_ROLES:
        raise AccountingValidationError(
            f"role must be one of {VALID_CONTACT_ROLES}, got: {role!r}."
        )
    return role


def tag_contact_role(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID, *, role: str
) -> ContactProfileView:
    """Creates the one `ContactProfile` a contact may have. Re-tagging an
    already-tagged contact is `update_contact_role()`, not this function
    -- mirrors `product/accounting/accounts.py`'s own "code is immutable,
    but the row can still be updated" shape, applied to `role` here."""
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="create")
    _validate_role(role)
    # Reuses CRM's own published accessor -- never touches crm.contacts
    # directly (module docstring). Propagates CrmReferenceNotFoundError/
    # CrmAccessDeniedError unchanged on an unknown/inaccessible contact.
    get_contact(actor_user_id, tenant_id, contact_id)

    profile_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            session.add(
                ContactProfile(id=profile_id, tenant_id=tenant_id, contact_id=contact_id, role=role)
            )
            session.flush()
    except IntegrityError as exc:
        raise AccountingConflictError("contact_id", str(contact_id)) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(ContactProfile, profile_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.contact_profile.created",
        resource_type="accounting.contact_profile",
        resource_id=str(profile_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"contact_id": str(contact_id), "role": role},
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, contact_id: uuid.UUID) -> ContactProfile:
    row = session.execute(
        select(ContactProfile).where(
            ContactProfile.tenant_id == tenant_id, ContactProfile.contact_id == contact_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise AccountingReferenceNotFoundError("contact_profile", contact_id)
    return row


def get_contact_role(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID
) -> ContactProfileView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, contact_id)
        session.expunge(row)
    return _to_view(row)


def update_contact_role(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, contact_id: uuid.UUID, *, role: str
) -> ContactProfileView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="update")
    _validate_role(role)
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, contact_id)
        row.role = role
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.contact_profile.updated",
        resource_type="accounting.contact_profile",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"role": role},
    )
    return _to_view(row)


def list_contact_roles(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    role: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[ContactProfileView]:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        query = select(ContactProfile).where(ContactProfile.tenant_id == tenant_id)
        if role is not None:
            query = query.where(ContactProfile.role == role)
        rows = (
            session.execute(
                query.order_by(ContactProfile.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def _assert_role(
    session, tenant_id: uuid.UUID, contact_id: uuid.UUID, *, required_role: str
) -> None:
    """Internal helper used by `invoices.py`/`bills.py`/`payments.py` to
    enforce Decision 6's own "customer/both required for an invoice,
    supplier/both for a bill" rule, without a second `require()`
    authorization check (the caller already authorized for
    `invoice.create`/`bill.create`/`payment.create`). Takes the caller's
    own `session` -- never opens a second, separate `tenant_session_scope()`
    -- both so this participates in the caller's own transaction (mirrors
    `journal.py`'s own private, session-taking helpers) and so `row.role`
    below is read while still attached to a live session, never after it
    has closed."""
    row = session.execute(
        select(ContactProfile).where(
            ContactProfile.tenant_id == tenant_id, ContactProfile.contact_id == contact_id
        )
    ).scalar_one_or_none()
    if row is None:
        raise AccountingValidationError(
            f"contact {contact_id} has no accounting role -- tag it via tag_contact_role() first."
        )
    if row.role != required_role and row.role != "both":
        raise AccountingValidationError(
            f"contact {contact_id} is tagged {row.role!r}, not {required_role!r} (or 'both')."
        )


__all__ = [
    "ContactProfileView",
    "get_contact_role",
    "list_contact_roles",
    "tag_contact_role",
    "update_contact_role",
]
