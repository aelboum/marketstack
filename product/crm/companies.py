"""Company CRUD (docs/ROADMAP.md Phase 4.1).

Every function follows the shape established by `product/agency
/provisioning.py::provision_client()`: authorize via `product.crm
.permissions.require()` first, then the actual `tenant_session_scope()`
read/write, then `core.audit_log.record()` for mutations. See
`docs/ADR/0002-...`'s Phase 4 addendum for why the authorization check
lives here rather than at the ingress layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError
from product.crm.models import ENTITY_TYPE_COMPANY, Company
from product.crm.pagination import DEFAULT_PAGE_SIZE, clamp_limit
from product.crm.permissions import COMPANY_RESOURCE, require
from product.crm.search import apply_custom_field_filters, apply_tag_filter, apply_text_search


@dataclass(frozen=True, slots=True)
class CompanyView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    domain: str | None
    phone: str | None
    created_at: datetime
    updated_at: datetime


def _to_view(row: Company) -> CompanyView:
    return CompanyView(
        id=row.id,
        tenant_id=row.tenant_id,
        name=row.name,
        domain=row.domain,
        phone=row.phone,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_company(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    name: str,
    domain: str | None = None,
    phone: str | None = None,
) -> CompanyView:
    require(actor_user_id, tenant_id, resource=COMPANY_RESOURCE, action="create")
    with tenant_session_scope(tenant_id) as session:
        row = Company(tenant_id=tenant_id, name=name, domain=domain, phone=phone)
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.company.create",
        resource_type="crm.company",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def get_company(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> CompanyView:
    require(actor_user_id, tenant_id, resource=COMPANY_RESOURCE, action="read")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Company, company_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("company", company_id)
        session.expunge(row)
    return _to_view(row)


def list_companies(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    q: str | None = None,
    tag: str | None = None,
    custom_field: list[str] | None = None,
) -> list[CompanyView]:
    require(actor_user_id, tenant_id, resource=COMPANY_RESOURCE, action="read")
    bounded_limit = clamp_limit(limit)
    with tenant_session_scope(tenant_id) as session:
        stmt = select(Company).where(Company.tenant_id == tenant_id)
        stmt = apply_text_search(stmt, Company, (Company.name, Company.domain), q)
        stmt = apply_tag_filter(stmt, Company, ENTITY_TYPE_COMPANY, tenant_id, tag)
        stmt = apply_custom_field_filters(
            stmt,
            Company,
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE_COMPANY,
            custom_field_params=custom_field,
            session=session,
        )
        rows = (
            session.execute(
                stmt.order_by(Company.created_at.desc()).limit(bounded_limit).offset(max(offset, 0))
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_to_view(row) for row in rows]


def update_company(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    name: str | None = None,
    domain: str | None = None,
    phone: str | None = None,
) -> CompanyView:
    require(actor_user_id, tenant_id, resource=COMPANY_RESOURCE, action="update")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Company, company_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("company", company_id)
        if name is not None:
            row.name = name
        if domain is not None:
            row.domain = domain
        if phone is not None:
            row.phone = phone
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.company.update",
        resource_type="crm.company",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
    )
    return _to_view(row)


def delete_company(actor_user_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
    require(actor_user_id, tenant_id, resource=COMPANY_RESOURCE, action="delete")
    with tenant_session_scope(tenant_id) as session:
        row = session.get(Company, company_id)
        if row is None or row.tenant_id != tenant_id:
            raise CrmReferenceNotFoundError("company", company_id)
        session.delete(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.company.delete",
        resource_type="crm.company",
        resource_id=str(company_id),
        outcome=AuditOutcome.SUCCESS,
    )
