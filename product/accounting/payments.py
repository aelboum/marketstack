"""Payments and allocations (ADR-0014 Decision 8 + its Phase 25
reconciliation addendum, docs/ROADMAP.md Phase 25).

**No cash-leg ledger posting** -- a `Payment` never creates a
`JournalEntry` this phase (Decision 8's own explicit exclusion; no bank/
cash GL account is designated yet). `Payment.unallocated_amount` is the
single source of truth for its own "status" -- no separate lifecycle
column (Decision 2's own denormalization discipline, applied here).

**Dual locking (the addendum's own correction to the original decision)**:
`create_allocation()`/`reverse_allocation()` acquire **both** the
payment's own tenant advisory lock and the target document's, in a fixed,
deterministic order (`sorted()` over the two lock-key strings) -- the
original decision locked only the document, missing the race between two
concurrent allocations *from the same payment* against two *different*
documents. Same `acquire_tenant_advisory_lock()` primitive throughout,
never a new locking abstraction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.audit_log import ActorType, AuditOutcome, record
from core.idempotency import run_idempotent
from infra.db import acquire_tenant_advisory_lock, select, tenant_session_scope

from product.accounting.contacts import _assert_role
from product.accounting.errors import AccountingReferenceNotFoundError, AccountingValidationError
from product.accounting.models import (
    ALLOCATION_DOCUMENT_TYPE_BILL,
    ALLOCATION_DOCUMENT_TYPE_INVOICE,
    CONTACT_ROLE_CUSTOMER,
    CONTACT_ROLE_SUPPLIER,
    DOCUMENT_STATUS_POSTED,
    PAYMENT_DIRECTION_INBOUND,
    VALID_ALLOCATION_DOCUMENT_TYPES,
    VALID_PAYMENT_DIRECTIONS,
    ZERO,
    Bill,
    Invoice,
    Payment,
    PaymentAllocation,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import PAYMENT_RESOURCE, require
from product.foundation.events import Event, publish
from product.foundation.values import Money

ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE = "accounting.payment.created"
ACCOUNTING_PAYMENT_CREATED_EVENT_VERSION = 1
ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE = "accounting.payment.allocated"
ACCOUNTING_PAYMENT_ALLOCATED_EVENT_VERSION = 1

_DOCUMENT_MODEL_BY_TYPE: dict[str, type] = {
    ALLOCATION_DOCUMENT_TYPE_INVOICE: Invoice,
    ALLOCATION_DOCUMENT_TYPE_BILL: Bill,
}


def _validate_currency(currency: str) -> str:
    normalized = currency.upper()
    Money(minor_units=0, currency=normalized)
    return normalized


def _validate_direction(direction: str) -> str:
    if direction not in VALID_PAYMENT_DIRECTIONS:
        raise AccountingValidationError(
            f"direction must be one of {VALID_PAYMENT_DIRECTIONS}, got: {direction!r}."
        )
    return direction


def _validate_document_type(document_type: str) -> str:
    if document_type not in VALID_ALLOCATION_DOCUMENT_TYPES:
        raise AccountingValidationError(
            f"document_type must be one of {VALID_ALLOCATION_DOCUMENT_TYPES}, got: "
            f"{document_type!r}."
        )
    return document_type


def _lock_payment_and_document(
    session, tenant_id: uuid.UUID, payment_id: uuid.UUID, document_id: uuid.UUID
) -> None:
    """Fixed, deterministic lock order -- see module docstring. Sorting
    the two full lock-key strings (rather than the raw ids) keeps the
    order stable regardless of which id happens to sort lower, and reads
    unambiguously at every call site."""
    payment_key = f"accounting.payment.{payment_id}"
    document_key = f"accounting.document.{document_id}"
    for key in sorted((payment_key, document_key)):
        acquire_tenant_advisory_lock(session, tenant_id, key)


@dataclass(frozen=True, slots=True)
class PaymentView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID
    direction: str
    amount: Decimal
    currency: str
    unallocated_amount: Decimal
    reference: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @property
    def is_fully_allocated(self) -> bool:
        """Derived, per Decision 8's own addendum -- never a stored
        column."""
        return self.unallocated_amount == ZERO


def _to_view(row: Payment) -> PaymentView:
    return PaymentView(
        id=row.id,
        tenant_id=row.tenant_id,
        contact_id=row.contact_id,
        direction=row.direction,
        amount=row.amount,
        currency=row.currency,
        unallocated_amount=row.unallocated_amount,
        reference=row.reference,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass(frozen=True, slots=True)
class PaymentAllocationView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    payment_id: uuid.UUID
    document_type: str
    document_id: uuid.UUID
    amount: Decimal
    reverses_allocation_id: uuid.UUID | None
    created_by_user_id: uuid.UUID
    created_at: datetime


def _allocation_to_view(row: PaymentAllocation) -> PaymentAllocationView:
    return PaymentAllocationView(
        id=row.id,
        tenant_id=row.tenant_id,
        payment_id=row.payment_id,
        document_type=row.document_type,
        document_id=row.document_id,
        amount=row.amount,
        reverses_allocation_id=row.reverses_allocation_id,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
    )


def _create_payment_in_session(
    session,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    direction: str,
    amount: Decimal,
    currency: str,
    reference: str | None,
) -> dict[str, object]:
    required_role = (
        CONTACT_ROLE_CUSTOMER if direction == PAYMENT_DIRECTION_INBOUND else CONTACT_ROLE_SUPPLIER
    )
    _assert_role(session, tenant_id, contact_id, required_role=required_role)
    payment_id = uuid.uuid4()
    session.add(
        Payment(
            id=payment_id,
            tenant_id=tenant_id,
            contact_id=contact_id,
            direction=direction,
            amount=amount,
            currency=currency,
            unallocated_amount=amount,
            reference=reference,
            created_by_user_id=actor_user_id,
        )
    )
    session.flush()
    return {"payment_id": str(payment_id)}


def create_payment(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    contact_id: uuid.UUID,
    direction: str,
    amount: Decimal,
    currency: str,
    reference: str | None = None,
    idempotency_key: str | None = None,
) -> PaymentView:
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="create")
    validated_direction = _validate_direction(direction)
    validated_currency = _validate_currency(currency)
    if not isinstance(amount, Decimal) or amount <= ZERO:
        raise AccountingValidationError("amount must be a positive Decimal.")

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _create_payment_in_session(
                session,
                tenant_id,
                actor_user_id,
                contact_id=contact_id,
                direction=validated_direction,
                amount=amount,
                currency=validated_currency,
                reference=reference,
            )
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _create_payment_in_session(
                session,
                tenant_id,
                actor_user_id,
                contact_id=contact_id,
                direction=validated_direction,
                amount=amount,
                currency=validated_currency,
                reference=reference,
            )

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.payment.create",
            idempotency_key,
            fingerprint_payload={
                "contact_id": str(contact_id),
                "direction": validated_direction,
                "amount": str(amount),
            },
            business_fn=_business,
        )

    payment_id = uuid.UUID(str(result["payment_id"]))
    view = _load_payment_view(tenant_id, payment_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.payment.created",
            resource_type="accounting.payment",
            resource_id=str(payment_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={"contact_id": str(contact_id), "direction": validated_direction},
        )
        publish(
            Event(
                type=ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE,
                version=ACCOUNTING_PAYMENT_CREATED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={"payment_id": str(payment_id), "contact_id": str(contact_id)},
            )
        )
    return view


def _load_payment_view(tenant_id: uuid.UUID, payment_id: uuid.UUID) -> PaymentView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Payment, payment_id)
        assert row is not None
        session.expunge(row)
    return _to_view(row)


def _get_owned_payment(session, tenant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
    row = session.get(Payment, payment_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("payment", payment_id)
    return row


def get_payment(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, payment_id: uuid.UUID
) -> PaymentView:
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_payment(session, tenant_id, payment_id)
        session.expunge(row)
    return _to_view(row)


def list_payments(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[PaymentView]:
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Payment)
                .where(Payment.tenant_id == tenant_id)
                .order_by(Payment.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def _create_allocation_in_session(
    session,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    *,
    payment_id: uuid.UUID,
    document_type: str,
    document_id: uuid.UUID,
    amount: Decimal,
) -> dict[str, object]:
    _lock_payment_and_document(session, tenant_id, payment_id, document_id)

    payment = session.get(Payment, payment_id)
    if payment is None or payment.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("payment", payment_id)
    if amount > payment.unallocated_amount:
        raise AccountingValidationError(
            f"allocation of {amount} exceeds payment {payment_id}'s own remaining "
            f"unallocated_amount ({payment.unallocated_amount})."
        )

    document_model = _DOCUMENT_MODEL_BY_TYPE[document_type]
    # Re-reads the target row through this same tenant's own session
    # before allocating (ADR-0014 Decision 8's own stated discipline) --
    # a cross-tenant target simply does not exist here, never merely
    # unauthorized.
    document = session.get(document_model, document_id)
    if document is None or document.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError(document_type, document_id)
    if document.status != DOCUMENT_STATUS_POSTED:
        raise AccountingValidationError(
            f"{document_type} {document_id} cannot be allocated against while "
            f"status={document.status!r} (only 'posted' documents can be)."
        )
    if amount > document.outstanding_amount:
        raise AccountingValidationError(
            f"allocation of {amount} exceeds {document_type} {document_id}'s own "
            f"remaining outstanding_amount ({document.outstanding_amount})."
        )

    payment.unallocated_amount = payment.unallocated_amount - amount
    document.outstanding_amount = document.outstanding_amount - amount

    allocation_id = uuid.uuid4()
    session.add(
        PaymentAllocation(
            id=allocation_id,
            tenant_id=tenant_id,
            payment_id=payment_id,
            document_type=document_type,
            document_id=document_id,
            amount=amount,
            created_by_user_id=actor_user_id,
        )
    )
    session.flush()
    return {"allocation_id": str(allocation_id)}


def create_allocation(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    payment_id: uuid.UUID,
    document_type: str,
    document_id: uuid.UUID,
    amount: Decimal,
    idempotency_key: str | None = None,
) -> PaymentAllocationView:
    """Rejects (never clamps) an amount exceeding either the payment's own
    remaining `unallocated_amount` or the document's own remaining
    `outstanding_amount`. Both are checked and updated inside the same
    dual-locked transaction (module docstring)."""
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="allocate")
    validated_type = _validate_document_type(document_type)
    if not isinstance(amount, Decimal) or amount <= ZERO:
        raise AccountingValidationError("amount must be a positive Decimal.")

    if idempotency_key is None:
        with tenant_session_scope(tenant_id) as session:
            result = _create_allocation_in_session(
                session,
                tenant_id,
                actor_user_id,
                payment_id=payment_id,
                document_type=validated_type,
                document_id=document_id,
                amount=amount,
            )
        is_replay = False
    else:

        def _business(session) -> dict[str, object]:
            return _create_allocation_in_session(
                session,
                tenant_id,
                actor_user_id,
                payment_id=payment_id,
                document_type=validated_type,
                document_id=document_id,
                amount=amount,
            )

        is_replay, result = run_idempotent(
            tenant_id,
            "accounting.payment.allocate",
            idempotency_key,
            fingerprint_payload={
                "payment_id": str(payment_id),
                "document_type": validated_type,
                "document_id": str(document_id),
                "amount": str(amount),
            },
            business_fn=_business,
        )

    allocation_id = uuid.UUID(str(result["allocation_id"]))
    view = _load_allocation_view(tenant_id, allocation_id)
    if not is_replay:
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.USER,
            actor_user_id=actor_user_id,
            action="accounting.payment_allocation.created",
            resource_type="accounting.payment_allocation",
            resource_id=str(allocation_id),
            outcome=AuditOutcome.SUCCESS,
            metadata={
                "payment_id": str(payment_id),
                "document_type": validated_type,
                "document_id": str(document_id),
            },
        )
        publish(
            Event(
                type=ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE,
                version=ACCOUNTING_PAYMENT_ALLOCATED_EVENT_VERSION,
                tenant_id=str(tenant_id),
                payload={
                    "payment_id": str(payment_id),
                    "document_type": validated_type,
                    "document_id": str(document_id),
                    "allocation_id": str(allocation_id),
                },
            )
        )
    return view


def _load_allocation_view(tenant_id: uuid.UUID, allocation_id: uuid.UUID) -> PaymentAllocationView:
    with tenant_session_scope(tenant_id) as session:
        row = session.get(PaymentAllocation, allocation_id)
        assert row is not None
        session.expunge(row)
    return _allocation_to_view(row)


def list_allocations_for_document(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    document_type: str,
    document_id: uuid.UUID,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[PaymentAllocationView]:
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(PaymentAllocation)
                .where(
                    PaymentAllocation.tenant_id == tenant_id,
                    PaymentAllocation.document_type == document_type,
                    PaymentAllocation.document_id == document_id,
                )
                .order_by(PaymentAllocation.created_at.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_allocation_to_view(row) for row in rows]


def _reverse_allocation_in_session(
    session, tenant_id: uuid.UUID, actor_user_id: uuid.UUID, allocation_id: uuid.UUID
) -> dict[str, object]:
    original = session.get(PaymentAllocation, allocation_id)
    if original is None or original.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("payment_allocation", allocation_id)
    if original.reverses_allocation_id is not None:
        raise AccountingValidationError(
            f"payment_allocation {allocation_id} is itself a reversal and cannot be reversed."
        )
    already_reversed = session.execute(
        select(PaymentAllocation.id).where(
            PaymentAllocation.tenant_id == tenant_id,
            PaymentAllocation.reverses_allocation_id == allocation_id,
        )
    ).scalar_one_or_none()
    if already_reversed is not None:
        raise AccountingValidationError(f"payment_allocation {allocation_id} was already reversed.")

    _lock_payment_and_document(session, tenant_id, original.payment_id, original.document_id)

    payment = session.get(Payment, original.payment_id)
    assert payment is not None and payment.tenant_id == tenant_id
    document_model = _DOCUMENT_MODEL_BY_TYPE[original.document_type]
    document = session.get(document_model, original.document_id)
    assert document is not None and document.tenant_id == tenant_id

    payment.unallocated_amount = payment.unallocated_amount + original.amount
    document.outstanding_amount = document.outstanding_amount + original.amount

    reversal_id = uuid.uuid4()
    session.add(
        PaymentAllocation(
            id=reversal_id,
            tenant_id=tenant_id,
            payment_id=original.payment_id,
            document_type=original.document_type,
            document_id=original.document_id,
            amount=original.amount,
            reverses_allocation_id=original.id,
            created_by_user_id=actor_user_id,
        )
    )
    session.flush()
    return {"reversal_allocation_id": str(reversal_id)}


def reverse_allocation(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, allocation_id: uuid.UUID
) -> PaymentAllocationView:
    """Creates a new record restoring the amount to both the payment and
    the document -- never an `UPDATE`/`DELETE` on the original row
    (mirrors `journal.py`'s own reversal-not-mutation discipline,
    ADR-0014 Decision 3, extended to this lighter-weight entity by the
    Decision 8 addendum). Owner-only (ADR-0014 Decision 13)."""
    require(actor_user_id, tenant_id, resource=PAYMENT_RESOURCE, action="reverse_allocation")
    with tenant_session_scope(tenant_id) as session:
        result = _reverse_allocation_in_session(session, tenant_id, actor_user_id, allocation_id)

    reversal_id = uuid.UUID(str(result["reversal_allocation_id"]))
    view = _load_allocation_view(tenant_id, reversal_id)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.payment_allocation.reversed",
        resource_type="accounting.payment_allocation",
        resource_id=str(allocation_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"reversal_allocation_id": str(reversal_id)},
    )
    return view


__all__ = [
    "ACCOUNTING_PAYMENT_ALLOCATED_EVENT_TYPE",
    "ACCOUNTING_PAYMENT_CREATED_EVENT_TYPE",
    "PaymentAllocationView",
    "PaymentView",
    "create_allocation",
    "create_payment",
    "get_payment",
    "list_allocations_for_document",
    "list_payments",
    "reverse_allocation",
]
