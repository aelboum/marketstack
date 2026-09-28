"""Tax-code catalog management (ADR-0014 Decision 7, docs/ROADMAP.md
Phase 25). No rate is ever seeded by this module -- a tenant creates its
own codes; no jurisdiction is assumed or hardcoded. `tax_account_id` is
required: a tax code's collected/paid amounts always post to a real GL
account (Decision 7's own "not a side-channel total" requirement).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import IntegrityError, select, tenant_session_scope

from product.accounting.errors import (
    AccountingConflictError,
    AccountingReferenceNotFoundError,
    AccountingValidationError,
)
from product.accounting.models import (
    MAX_TAX_CODE_LENGTH,
    MAX_TAX_NAME_LENGTH,
    VALID_TAX_TYPES,
    Account,
    TaxCode,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import INVOICE_RESOURCE, require


def _date_to_utc_midnight(value: date) -> datetime:
    return datetime(value.year, value.month, value.day, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TaxCodeView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    rate_percent: Decimal
    tax_type: str
    tax_account_id: uuid.UUID
    is_active: bool
    effective_from: date | None
    effective_to: date | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: TaxCode) -> TaxCodeView:
    return TaxCodeView(
        id=row.id,
        tenant_id=row.tenant_id,
        code=row.code,
        name=row.name,
        rate_percent=row.rate_percent,
        tax_type=row.tax_type,
        tax_account_id=row.tax_account_id,
        is_active=row.is_active,
        effective_from=row.effective_from.date() if row.effective_from else None,
        effective_to=row.effective_to.date() if row.effective_to else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_code(code: str) -> str:
    if not isinstance(code, str) or not code.strip():
        raise AccountingValidationError("code must be a non-empty string.")
    if len(code) > MAX_TAX_CODE_LENGTH:
        raise AccountingValidationError(f"code must be at most {MAX_TAX_CODE_LENGTH} characters.")
    return code.strip()


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AccountingValidationError("name must be a non-empty string.")
    if len(name) > MAX_TAX_NAME_LENGTH:
        raise AccountingValidationError(f"name must be at most {MAX_TAX_NAME_LENGTH} characters.")
    return name.strip()


def _validate_tax_type(tax_type: str) -> str:
    if tax_type not in VALID_TAX_TYPES:
        raise AccountingValidationError(
            f"tax_type must be one of {VALID_TAX_TYPES}, got: {tax_type!r}."
        )
    return tax_type


def _validate_rate(rate_percent: Decimal) -> Decimal:
    if not isinstance(rate_percent, Decimal):
        raise AccountingValidationError("rate_percent must be a Decimal.")
    if rate_percent < 0:
        raise AccountingValidationError("rate_percent must not be negative.")
    return rate_percent


def create_tax_code(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    code: str,
    name: str,
    rate_percent: Decimal,
    tax_type: str,
    tax_account_id: uuid.UUID,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> TaxCodeView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="create")
    validated_code = _validate_code(code)
    validated_name = _validate_name(name)
    validated_type = _validate_tax_type(tax_type)
    validated_rate = _validate_rate(rate_percent)
    if effective_to is not None and effective_from is not None and effective_to < effective_from:
        raise AccountingValidationError("effective_to must not be before effective_from.")

    tax_code_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            account = session.get(Account, tax_account_id)
            if account is None or account.tenant_id != tenant_id:
                raise AccountingReferenceNotFoundError("account", tax_account_id)
            session.add(
                TaxCode(
                    id=tax_code_id,
                    tenant_id=tenant_id,
                    code=validated_code,
                    name=validated_name,
                    rate_percent=validated_rate,
                    tax_type=validated_type,
                    tax_account_id=tax_account_id,
                    effective_from=_date_to_utc_midnight(effective_from)
                    if effective_from
                    else None,
                    effective_to=_date_to_utc_midnight(effective_to) if effective_to else None,
                )
            )
            session.flush()
    except IntegrityError as exc:
        raise AccountingConflictError("code", validated_code) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(TaxCode, tax_code_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.tax_code.created",
        resource_type="accounting.tax_code",
        resource_id=str(tax_code_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"code": validated_code, "tax_type": validated_type},
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, tax_code_id: uuid.UUID) -> TaxCode:
    row = session.get(TaxCode, tax_code_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("tax_code", tax_code_id)
    return row


def get_tax_code(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, tax_code_id: uuid.UUID
) -> TaxCodeView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, tax_code_id)
        session.expunge(row)
    return _to_view(row)


def list_tax_codes(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[TaxCodeView]:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(TaxCode)
                .where(TaxCode.tenant_id == tenant_id)
                .order_by(TaxCode.code.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def deactivate_tax_code(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, tax_code_id: uuid.UUID
) -> TaxCodeView:
    require(actor_user_id, tenant_id, resource=INVOICE_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, tax_code_id)
        row.is_active = False
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.tax_code.deactivated",
        resource_type="accounting.tax_code",
        resource_id=str(tax_code_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return _to_view(row)


__all__ = [
    "TaxCodeView",
    "create_tax_code",
    "deactivate_tax_code",
    "get_tax_code",
    "list_tax_codes",
]
