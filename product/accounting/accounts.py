"""Chart-of-accounts management (docs/ROADMAP.md Phase 24, ADR-0014
Decision 2's own ledger target). Every mutating/read function authorizes
via `product.accounting.permissions.require()` first, then the actual
database access, then `core.audit_log.record()` for mutations --
mirrors `product/billing/resale_plans.py`'s own discipline exactly.

**No delete function this phase**, deliberately: ADR-0014 Decision 9
requires that an account referenced by any posted journal line can never
be deleted from under it (`journal_lines.account_id`'s own default-
`RESTRICT` foreign key, `product/accounting/models.py`), and this phase
does not build the "delete only if never referenced" special case that
would require -- `deactivate_account()`/`reactivate_account()` (the
`is_active` flag) cover the practical need (an account no longer offered
for new postings) without it. Mirrors
`product/billing/resale_plans.py::deactivate_resale_plan()`'s own
identical "no delete, a status flag instead" precedent.
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
from product.accounting.models import (
    MAX_ACCOUNT_CODE_LENGTH,
    MAX_ACCOUNT_NAME_LENGTH,
    VALID_ACCOUNT_TYPES,
    Account,
)
from product.accounting.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.accounting.permissions import ACCOUNT_RESOURCE, require


@dataclass(frozen=True, slots=True)
class AccountView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    code: str
    name: str
    account_type: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


def _to_view(row: Account) -> AccountView:
    return AccountView(
        id=row.id,
        tenant_id=row.tenant_id,
        code=row.code,
        name=row.name,
        account_type=row.account_type,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _validate_code(code: str) -> str:
    if not isinstance(code, str) or not code.strip():
        raise AccountingValidationError("code must be a non-empty string.")
    if len(code) > MAX_ACCOUNT_CODE_LENGTH:
        raise AccountingValidationError(
            f"code must be at most {MAX_ACCOUNT_CODE_LENGTH} characters."
        )
    return code.strip()


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AccountingValidationError("name must be a non-empty string.")
    if len(name) > MAX_ACCOUNT_NAME_LENGTH:
        raise AccountingValidationError(
            f"name must be at most {MAX_ACCOUNT_NAME_LENGTH} characters."
        )
    return name.strip()


def _validate_account_type(account_type: str) -> str:
    if account_type not in VALID_ACCOUNT_TYPES:
        raise AccountingValidationError(
            f"account_type must be one of {VALID_ACCOUNT_TYPES}, got: {account_type!r}."
        )
    return account_type


def create_account(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    code: str,
    name: str,
    account_type: str,
) -> AccountView:
    require(actor_user_id, tenant_id, resource=ACCOUNT_RESOURCE, action="create")
    validated_code = _validate_code(code)
    validated_name = _validate_name(name)
    validated_account_type = _validate_account_type(account_type)

    account_id = uuid.uuid4()
    try:
        with tenant_session_scope(tenant_id) as session:
            session.add(
                Account(
                    id=account_id,
                    tenant_id=tenant_id,
                    code=validated_code,
                    name=validated_name,
                    account_type=validated_account_type,
                )
            )
            session.flush()
    except IntegrityError as exc:
        raise AccountingConflictError("code", validated_code) from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.get(Account, account_id)
        assert row is not None
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.account.created",
        resource_type="accounting.account",
        resource_id=str(account_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"code": validated_code, "account_type": validated_account_type},
    )
    return _to_view(row)


def _get_owned_row(session, tenant_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    row = session.get(Account, account_id)
    if row is None or row.tenant_id != tenant_id:
        raise AccountingReferenceNotFoundError("account", account_id)
    return row


def get_account(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> AccountView:
    require(actor_user_id, tenant_id, resource=ACCOUNT_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, account_id)
        session.expunge(row)
    return _to_view(row)


def list_accounts(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[AccountView]:
    require(actor_user_id, tenant_id, resource=ACCOUNT_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(Account)
                .where(Account.tenant_id == tenant_id)
                .order_by(Account.code.asc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_account(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    name: str | None = None,
) -> AccountView:
    """Renames an account. `code`/`account_type` are immutable after
    creation -- changing either retroactively would change what every
    already-posted journal line referencing this account means, which
    this phase never does (mirrors ADR-0014 Decision 3's own "posted
    means posted" discipline, applied here to the account's own identity
    rather than a journal entry's)."""
    require(actor_user_id, tenant_id, resource=ACCOUNT_RESOURCE, action="update")
    validated_name = _validate_name(name) if name is not None else None
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, account_id)
        if validated_name is not None:
            row.name = validated_name
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="accounting.account.updated",
        resource_type="accounting.account",
        resource_id=str(account_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return _to_view(row)


def _set_active(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, account_id: uuid.UUID, *, is_active: bool
) -> AccountView:
    require(actor_user_id, tenant_id, resource=ACCOUNT_RESOURCE, action="update")
    action = "accounting.account.reactivated" if is_active else "accounting.account.deactivated"
    with tenant_session_scope(tenant_id) as session:
        row = _get_owned_row(session, tenant_id, account_id)
        row.is_active = is_active
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action=action,
        resource_type="accounting.account",
        resource_id=str(account_id),
        outcome=AuditOutcome.SUCCESS,
        metadata={},
    )
    return _to_view(row)


def deactivate_account(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> AccountView:
    """Sets `is_active=False` -- no longer offered for new journal lines
    (`product/accounting/journal.py::create_journal_entry()` checks this).
    Existing posted lines referencing it are unaffected."""
    return _set_active(actor_user_id, tenant_id, account_id, is_active=False)


def reactivate_account(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, account_id: uuid.UUID
) -> AccountView:
    return _set_active(actor_user_id, tenant_id, account_id, is_active=True)


__all__ = [
    "AccountView",
    "create_account",
    "deactivate_account",
    "get_account",
    "list_accounts",
    "reactivate_account",
    "update_account",
]
