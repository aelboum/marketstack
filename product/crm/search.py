"""Shared search/filter helpers for the CRM list endpoints
(docs/ROADMAP.md Phase 4.4).

**Injection-safety discipline (the roadmap's own explicit requirement):**
every filter value below reaches the database exclusively as a bound
SQLAlchemy parameter (`Column.ilike(value)`, `Column == value`) -- never
string-concatenated into SQL text. A `custom_field` filter's
`field_definition_id` is always resolved through a parameterized lookup
first (and checked against `tenant_id`/`entity_type` before use); the
field's own tenant-supplied *name* is never read at filter time at all --
only its `field_type` (one of four fixed, code-controlled strings) decides
which of the four fixed, typed `CustomFieldValue` columns
(`value_text`/`value_number`/`value_date`/`value_boolean`) is filtered.
There is no code path anywhere in this module that builds a column
reference, a table name, or a fragment of SQL text from caller-supplied
data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from infra.db import select

from product.crm.errors import CrmReferenceNotFoundError, CrmValidationError
from product.crm.models import (
    FIELD_TYPE_BOOLEAN,
    FIELD_TYPE_DATE,
    FIELD_TYPE_NUMBER,
    FIELD_TYPE_TEXT,
    CustomFieldDefinition,
    CustomFieldValue,
    EntityTag,
    Tag,
)


def apply_text_search(stmt, model, columns: tuple, q: str | None):
    """OR the given `q` substring across `columns` (each an ORM column
    attribute on `model`), via `.ilike()` -- always a bound parameter,
    never a formatted/concatenated LIKE pattern. `%`/`_` in `q` are
    literal ILIKE wildcard characters (Postgres' own ILIKE semantics,
    not something this function escapes) -- a caller searching for a
    literal `%` matches any single character there, exactly as typing
    `%` into any ILIKE-backed search box would; this is documented
    behavior, not an injection risk (the value is still only ever a bound
    parameter, never interpreted as SQL)."""
    if not q or not columns:
        return stmt
    pattern = f"%{q}%"
    condition = columns[0].ilike(pattern)
    for column in columns[1:]:
        condition = condition | column.ilike(pattern)
    return stmt.where(condition)


def apply_tag_filter(stmt, model, entity_type: str, tenant_id: uuid.UUID, tag_name: str | None):
    """Restrict to rows carrying a tag named exactly `tag_name` (an exact,
    bound-parameter match against `crm.tags.name` -- never a substring or
    pattern match for tag filtering). `entity_type` selects which of
    `EntityTag.contact_id`/`company_id`/`opportunity_id` links back to
    `model.id` -- resolved via `getattr()` against a fixed attribute name
    this module controls, never a caller-supplied string used as a column
    name directly."""
    if not tag_name:
        return stmt
    entity_tag_column = getattr(EntityTag, f"{entity_type}_id")
    matching_ids = (
        select(entity_tag_column)
        .select_from(EntityTag.__table__.join(Tag.__table__, EntityTag.tag_id == Tag.id))
        .where(Tag.tenant_id == tenant_id, Tag.name == tag_name)
    )
    return stmt.where(model.id.in_(matching_ids))


def _coerce_filter_value(field_type: str, raw_value: str):
    if field_type == FIELD_TYPE_NUMBER:
        try:
            return float(raw_value)
        except ValueError as exc:
            raise CrmValidationError(
                f"custom_field value must be numeric, got: {raw_value!r}"
            ) from exc
    if field_type == FIELD_TYPE_BOOLEAN:
        lowered = raw_value.strip().lower()
        if lowered not in ("true", "false"):
            raise CrmValidationError(
                f"custom_field value must be 'true'/'false', got: {raw_value!r}"
            )
        return lowered == "true"
    if field_type == FIELD_TYPE_DATE:
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError as exc:
            raise CrmValidationError(
                f"custom_field value must be ISO-8601, got: {raw_value!r}"
            ) from exc
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return raw_value  # FIELD_TYPE_TEXT


def apply_custom_field_filters(
    stmt,
    model,
    *,
    tenant_id: uuid.UUID,
    entity_type: str,
    custom_field_params: list[str] | None,
    session,
):
    """Apply zero or more `"<definition_id>:<value>"` filters. Each
    `definition_id` is resolved via a parameterized lookup, checked
    against `tenant_id`/`entity_type` before use (`CrmReferenceNotFoundError`
    if it doesn't resolve there) -- never trusted merely because it is
    syntactically a UUID."""
    if not custom_field_params:
        return stmt
    for raw in custom_field_params:
        if ":" not in raw:
            raise CrmValidationError(
                f"custom_field filter must be '<definition_id>:<value>', got: {raw!r}"
            )
        raw_id, raw_value = raw.split(":", 1)
        try:
            definition_id = uuid.UUID(raw_id)
        except ValueError as exc:
            raise CrmValidationError(f"custom_field filter id is not a UUID: {raw_id!r}") from exc
        definition = session.get(CustomFieldDefinition, definition_id)
        if (
            definition is None
            or definition.tenant_id != tenant_id
            or definition.entity_type != entity_type
        ):
            raise CrmReferenceNotFoundError("custom_field_definition", definition_id)
        value = _coerce_filter_value(definition.field_type, raw_value)
        value_column = {
            FIELD_TYPE_TEXT: CustomFieldValue.value_text,
            FIELD_TYPE_NUMBER: CustomFieldValue.value_number,
            FIELD_TYPE_DATE: CustomFieldValue.value_date,
            FIELD_TYPE_BOOLEAN: CustomFieldValue.value_boolean,
        }[definition.field_type]
        if definition.field_type == FIELD_TYPE_TEXT:
            value_condition = value_column.ilike(f"%{value}%")
        else:
            value_condition = value_column == value
        value_entity_column = getattr(CustomFieldValue, f"{entity_type}_id")
        matching_ids = select(value_entity_column).where(
            CustomFieldValue.tenant_id == tenant_id,
            CustomFieldValue.field_definition_id == definition_id,
            value_condition,
        )
        stmt = stmt.where(model.id.in_(matching_ids))
    return stmt
