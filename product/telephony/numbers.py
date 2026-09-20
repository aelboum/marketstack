"""Phone number provisioning/assignment and routing-target configuration
(docs/ROADMAP.md Phase 8.1).

**`PhoneNumber` lives in a plain, untenanted `infra.db.session_scope()`,
never `tenant_session_scope()`** -- it is deliberately NOT RLS-scoped (see
`product/telephony/models.py`'s own module docstring), so every function
here that touches it filters by `tenant_id` explicitly in the query itself
-- mirrors `product/appointments/calendars.py::get_or_create_booking_link()`'s
identical treatment of `BookingLink`.

**`provision_phone_number()`/`release_phone_number()` take `provider` as a
required keyword argument with no default** -- there is no real default
`TelephonyProvider` configured (`product/telephony/provider.py`'s own
module docstring); only a test supplies `FakeTelephonyProvider` today.
This is why no HTTP route exposes either function (`product/telephony
/__init__.py`'s own module docstring).

**Routing targets are ordinary RLS-scoped data** (`PhoneNumberRoutingTarget`)
-- once `phone_number_id` is resolved via the untenanted lookup above,
everything else uses `tenant_session_scope(tenant_id)` like every other
product module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from core.rbac import can
from infra.db import select, session_scope, tenant_session_scope

from product.telephony.errors import (
    TelephonyReferenceNotFoundError,
    TelephonyValidationError,
)
from product.telephony.models import (
    STATUS_NUMBER_ACTIVE,
    STATUS_NUMBER_RELEASED,
    PhoneNumber,
    PhoneNumberRoutingTarget,
)
from product.telephony.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.telephony.permissions import CALL_RESOURCE, PHONE_NUMBER_RESOURCE, require
from product.telephony.provider import TelephonyProvider

MAX_ROUTING_TARGETS = 50


def _validate_user_reachable(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """The real IDOR-adjacent check -- `core.users` is a global table, so
    this is the only enforcement. Mirrors `product/appointments/calendars.py
    ::_validate_owner_membership()`'s identical reasoning and lowest-bar
    permission choice exactly (`core.rbac.can()` already accounts for both
    direct membership and inherited SUBTREE reach)."""
    if not can(actor_id=user_id, tenant_id=tenant_id, action="read", resource=CALL_RESOURCE):
        raise TelephonyReferenceNotFoundError("user", user_id)


@dataclass(frozen=True, slots=True)
class PhoneNumberView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone_number: str
    provider_name: str
    provider_number_id: str
    status: str
    created_at: datetime
    updated_at: datetime


def _to_view(row: PhoneNumber) -> PhoneNumberView:
    return PhoneNumberView(
        id=row.id,
        tenant_id=row.tenant_id,
        phone_number=row.phone_number,
        provider_name=row.provider_name,
        provider_number_id=row.provider_number_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def provision_phone_number(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    country_code: str,
    provider: TelephonyProvider,
) -> PhoneNumberView:
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="create")
    provisioned = provider.provision_number(country_code=country_code)
    with session_scope() as session:
        row = PhoneNumber(
            tenant_id=tenant_id,
            phone_number=provisioned.phone_number,
            provider_name=provider.name,
            provider_number_id=provisioned.provider_number_id,
            status=STATUS_NUMBER_ACTIVE,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.phone_number.provision",
        resource_type="telephony.phone_number",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        # Identifier only -- never the phone number string itself, per
        # this phase's own PII/audit discipline.
        metadata={"provider_name": provider.name},
    )
    return _to_view(row)


def get_phone_number(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, phone_number_id: uuid.UUID
) -> PhoneNumberView:
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="read")
    with session_scope() as session:
        row = session.get(PhoneNumber, phone_number_id)
        if row is None or row.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("phone_number", phone_number_id)
        session.expunge(row)
    return _to_view(row)


def list_phone_numbers(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> list[PhoneNumberView]:
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with session_scope() as session:
        rows = (
            session.execute(
                select(PhoneNumber)
                .where(PhoneNumber.tenant_id == tenant_id)
                .order_by(PhoneNumber.created_at.desc())
                .limit(bounded_limit)
                .offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def release_phone_number(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    phone_number_id: uuid.UUID,
) -> PhoneNumberView:
    """Soft-release (`status = 'released'`), never a hard delete -- a
    released number's `Call`/`PhoneNumberRoutingTarget` history must
    survive it, the identical reasoning `appointments.calendar_id`'s own
    undecided-delete-semantics disclosure already documents (never
    silently building cascading deletion this phase does not need)."""
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="delete")
    with session_scope() as session:
        row = session.get(PhoneNumber, phone_number_id)
        if row is None or row.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("phone_number", phone_number_id)
        row.status = STATUS_NUMBER_RELEASED
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.phone_number.release",
        resource_type="telephony.phone_number",
        resource_id=str(phone_number_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


@dataclass(frozen=True, slots=True)
class RoutingTargetView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone_number_id: uuid.UUID
    user_id: uuid.UUID
    position: int


def _routing_target_to_view(row: PhoneNumberRoutingTarget) -> RoutingTargetView:
    return RoutingTargetView(
        id=row.id,
        tenant_id=row.tenant_id,
        phone_number_id=row.phone_number_id,
        user_id=row.user_id,
        position=row.position,
    )


def _require_phone_number_in_tenant(tenant_id: uuid.UUID, phone_number_id: uuid.UUID) -> None:
    with session_scope() as session:
        row = session.get(PhoneNumber, phone_number_id)
        if row is None or row.tenant_id != tenant_id:
            raise TelephonyReferenceNotFoundError("phone_number", phone_number_id)


def add_routing_target(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    phone_number_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> RoutingTargetView:
    """Appends `user_id` at the next available `position` (0-indexed,
    lowest-first) for `phone_number_id`'s own routing list -- see
    `product/telephony/routing.py`'s own module docstring for how
    `position` is used (round-robin tie-break order)."""
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="update")
    _require_phone_number_in_tenant(tenant_id, phone_number_id)
    _validate_user_reachable(tenant_id, user_id)
    with tenant_session_scope(tenant_id) as session:
        existing_count = len(
            session.execute(
                select(PhoneNumberRoutingTarget).where(
                    PhoneNumberRoutingTarget.tenant_id == tenant_id,
                    PhoneNumberRoutingTarget.phone_number_id == phone_number_id,
                )
            )
            .scalars()
            .all()
        )
        if existing_count >= MAX_ROUTING_TARGETS:
            raise TelephonyValidationError(
                f"phone number {phone_number_id} already has the maximum of "
                f"{MAX_ROUTING_TARGETS} routing targets."
            )
        row = PhoneNumberRoutingTarget(
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            user_id=user_id,
            position=existing_count,
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.routing_target.add",
        resource_type="telephony.phone_number",
        resource_id=str(phone_number_id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _routing_target_to_view(row)


def list_routing_targets(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, phone_number_id: uuid.UUID
) -> list[RoutingTargetView]:
    require(actor_user_id, tenant_id, resource=PHONE_NUMBER_RESOURCE, action="read")
    _require_phone_number_in_tenant(tenant_id, phone_number_id)
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(PhoneNumberRoutingTarget)
                .where(
                    PhoneNumberRoutingTarget.tenant_id == tenant_id,
                    PhoneNumberRoutingTarget.phone_number_id == phone_number_id,
                )
                .order_by(PhoneNumberRoutingTarget.position.asc())
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_routing_target_to_view(row) for row in rows]


__all__ = [
    "MAX_ROUTING_TARGETS",
    "PhoneNumberView",
    "RoutingTargetView",
    "add_routing_target",
    "get_phone_number",
    "list_phone_numbers",
    "list_routing_targets",
    "provision_phone_number",
    "release_phone_number",
]
