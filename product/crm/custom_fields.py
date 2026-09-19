"""Tenant-defined custom fields (docs/ROADMAP.md Phase 4.4).

A typed key/value table split (`CustomFieldDefinition` + `CustomFieldValue`),
never JSONB with dynamic keys and never a dynamically-named column -- the
roadmap's own explicit requirement: "a tenant defining a custom field
must not be able to collide with a reserved column name or inject into
the search query path -- parameterized queries only, no dynamic SQL from
tenant-supplied field names." A field's `name` is stored data, never
interpolated into SQL or used to look up a column/attribute by string
manipulation -- every value read/write always targets one of four fixed,
typed columns (`value_text`/`value_number`/`value_date`/`value_boolean`),
chosen by this module's own code based on the definition's `field_type`,
with the actual value passed as a bound parameter.

Defining a field (`define_field`) requires `CUSTOM_FIELD_DEFINITION_RESOURCE`
(a tenant-level schema-configuration action). Setting/reading a *value* on
a specific entity reuses that entity's own `update`/`read` permission
(`product/crm/permissions.py`'s consolidation principle) -- `_entity_resource()`
below resolves which of `CONTACT_RESOURCE`/`COMPANY_RESOURCE`/
`OPPORTUNITY_RESOURCE` applies for a given `entity_type` string.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import (
    ENTITY_TYPE_COMPANY,
    ENTITY_TYPE_CONTACT,
    ENTITY_TYPE_OPPORTUNITY,
    FIELD_TYPE_BOOLEAN,
    FIELD_TYPE_DATE,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_TEXT,
    Company,
    Contact,
    CustomFieldDefinition,
    CustomFieldValue,
    Opportunity,
)
from product.crm.permissions import (
    COMPANY_RESOURCE,
    CONTACT_RESOURCE,
    CUSTOM_FIELD_DEFINITION_RESOURCE,
    OPPORTUNITY_RESOURCE,
    require,
)

_ENTITY_TYPES = (ENTITY_TYPE_CONTACT, ENTITY_TYPE_COMPANY, ENTITY_TYPE_OPPORTUNITY)
_FIELD_TYPES = (FIELD_TYPE_TEXT, FIELD_TYPE_NUMBER, FIELD_TYPE_DATE, FIELD_TYPE_BOOLEAN)

_ENTITY_RESOURCE_BY_TYPE = {
    ENTITY_TYPE_CONTACT: CONTACT_RESOURCE,
    ENTITY_TYPE_COMPANY: COMPANY_RESOURCE,
    ENTITY_TYPE_OPPORTUNITY: OPPORTUNITY_RESOURCE,
}
_ENTITY_MODEL_BY_TYPE = {
    ENTITY_TYPE_CONTACT: Contact,
    ENTITY_TYPE_COMPANY: Company,
    ENTITY_TYPE_OPPORTUNITY: Opportunity,
}


def _entity_resource(entity_type: str) -> str:
    resource = _ENTITY_RESOURCE_BY_TYPE.get(entity_type)
    if resource is None:
        raise CrmValidationError(
            f"entity_type must be one of {_ENTITY_TYPES}, got: {entity_type!r}"
        )
    return resource


def _require_entity_in_tenant(
    session, tenant_id: uuid.UUID, entity_type: str, entity_id: uuid.UUID
):
    model = _ENTITY_MODEL_BY_TYPE[entity_type]
    row = session.get(model, entity_id)
    if row is None or row.tenant_id != tenant_id:
        raise CrmReferenceNotFoundError(entity_type, entity_id)
    return row


@dataclass(frozen=True, slots=True)
class CustomFieldDefinitionView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    entity_type: str
    name: str
    field_type: str
    created_at: datetime


def _definition_view(row: CustomFieldDefinition) -> CustomFieldDefinitionView:
    return CustomFieldDefinitionView(
        id=row.id,
        tenant_id=row.tenant_id,
        entity_type=row.entity_type,
        name=row.name,
        field_type=row.field_type,
        created_at=row.created_at,
    )


def define_field(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    name: str,
    field_type: str,
) -> CustomFieldDefinitionView:
    require(actor_user_id, tenant_id, resource=CUSTOM_FIELD_DEFINITION_RESOURCE, action="create")
    if entity_type not in _ENTITY_TYPES:
        raise CrmValidationError(
            f"entity_type must be one of {_ENTITY_TYPES}, got: {entity_type!r}"
        )
    if field_type not in _FIELD_TYPES:
        raise CrmValidationError(f"field_type must be one of {_FIELD_TYPES}, got: {field_type!r}")
    with tenant_session_scope(tenant_id) as session:
        row = CustomFieldDefinition(
            tenant_id=tenant_id, entity_type=entity_type, name=name, field_type=field_type
        )
        session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.custom_field_definition.create",
        resource_type="crm.custom_field_definition",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"entity_type": entity_type, "field_type": field_type},
    )
    return _definition_view(row)


def list_field_definitions(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, entity_type: str
) -> list[CustomFieldDefinitionView]:
    require(actor_user_id, tenant_id, resource=CUSTOM_FIELD_DEFINITION_RESOURCE, action="read")
    if entity_type not in _ENTITY_TYPES:
        raise CrmValidationError(
            f"entity_type must be one of {_ENTITY_TYPES}, got: {entity_type!r}"
        )
    with tenant_session_scope(tenant_id) as session:
        rows = (
            session.execute(
                select(CustomFieldDefinition).where(
                    CustomFieldDefinition.tenant_id == tenant_id,
                    CustomFieldDefinition.entity_type == entity_type,
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_definition_view(row) for row in rows]


@dataclass(frozen=True, slots=True)
class CustomFieldValueView:
    id: uuid.UUID
    tenant_id: uuid.UUID
    field_definition_id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    value: object


def _value_view(
    row: CustomFieldValue, entity_type: str, entity_id: uuid.UUID
) -> CustomFieldValueView:
    if row.value_text is not None:
        value: object = row.value_text
    elif row.value_number is not None:
        value = row.value_number
    elif row.value_date is not None:
        value = row.value_date
    else:
        value = row.value_boolean
    return CustomFieldValueView(
        id=row.id,
        tenant_id=row.tenant_id,
        field_definition_id=row.field_definition_id,
        entity_type=entity_type,
        entity_id=entity_id,
        value=value,
    )


def _coerce_value(
    field_type: str, raw_value: object
) -> tuple[str | None, float | None, datetime | None, bool | None]:
    """Route `raw_value` to exactly one of the four typed columns,
    matching `field_type` -- never a dynamic column name, always one of
    these four fixed attributes. Rejects a value that doesn't match
    (e.g. a non-numeric string for a `"number"` field)."""
    if field_type == FIELD_TYPE_TEXT:
        if not isinstance(raw_value, str):
            raise CrmValidationError(f"value for a text field must be a string, got: {raw_value!r}")
        return raw_value, None, None, None
    if field_type == FIELD_TYPE_NUMBER:
        try:
            number = float(raw_value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise CrmValidationError(
                f"value for a number field must be numeric, got: {raw_value!r}"
            ) from exc
        return None, number, None, None
    if field_type == FIELD_TYPE_DATE:
        if isinstance(raw_value, datetime):
            date_value = raw_value
        elif isinstance(raw_value, str):
            try:
                date_value = datetime.fromisoformat(raw_value)
            except ValueError as exc:
                raise CrmValidationError(
                    f"value for a date field must be ISO-8601, got: {raw_value!r}"
                ) from exc
        else:
            raise CrmValidationError(
                f"value for a date field must be a date/ISO-8601 string, got: {raw_value!r}"
            )
        if date_value.tzinfo is None:
            date_value = date_value.replace(tzinfo=UTC)
        return None, None, date_value, None
    # FIELD_TYPE_BOOLEAN
    if not isinstance(raw_value, bool):
        raise CrmValidationError(f"value for a boolean field must be a bool, got: {raw_value!r}")
    return None, None, None, raw_value


def set_field_value(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    field_definition_id: uuid.UUID,
    value: object,
) -> CustomFieldValueView:
    resource = _entity_resource(entity_type)
    require(actor_user_id, tenant_id, resource=resource, action="update")
    with tenant_session_scope(tenant_id) as session:
        _require_entity_in_tenant(session, tenant_id, entity_type, entity_id)
        definition = session.get(CustomFieldDefinition, field_definition_id)
        if (
            definition is None
            or definition.tenant_id != tenant_id
            or definition.entity_type != entity_type
        ):
            raise CrmReferenceNotFoundError("custom_field_definition", field_definition_id)
        value_text, value_number, value_date, value_boolean = _coerce_value(
            definition.field_type, value
        )

        kwargs = {f"{entity_type}_id": entity_id}
        existing = (
            session.execute(
                select(CustomFieldValue).where(
                    CustomFieldValue.tenant_id == tenant_id,
                    CustomFieldValue.field_definition_id == field_definition_id,
                    *(getattr(CustomFieldValue, k) == v for k, v in kwargs.items()),
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None:
            existing.value_text = value_text
            existing.value_number = value_number
            existing.value_date = value_date
            existing.value_boolean = value_boolean
            row = existing
        else:
            row = CustomFieldValue(
                tenant_id=tenant_id,
                field_definition_id=field_definition_id,
                value_text=value_text,
                value_number=value_number,
                value_date=value_date,
                value_boolean=value_boolean,
                **kwargs,
            )
            session.add(row)
        session.flush()
        session.refresh(row)
        session.expunge(row)
    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="crm.custom_field_value.set",
        resource_type="crm.custom_field_value",
        resource_id=str(row.id),
        outcome=AuditOutcome.SUCCESS,
        metadata={"field_definition_id": str(field_definition_id)},
    )
    return _value_view(row, entity_type, entity_id)


def get_field_values(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, entity_type: str, entity_id: uuid.UUID
) -> list[CustomFieldValueView]:
    resource = _entity_resource(entity_type)
    require(actor_user_id, tenant_id, resource=resource, action="read")
    with tenant_session_scope(tenant_id) as session:
        _require_entity_in_tenant(session, tenant_id, entity_type, entity_id)
        entity_column = getattr(CustomFieldValue, f"{entity_type}_id")
        rows = (
            session.execute(
                select(CustomFieldValue).where(
                    CustomFieldValue.tenant_id == tenant_id, entity_column == entity_id
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            session.expunge(row)
    return [_value_view(row, entity_type, entity_id) for row in rows]
