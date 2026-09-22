"""Snapshot payload schema and versioning (docs/ROADMAP.md Phase 14,
"Configuration schema/versioning": "the schema version must allow future
migrations of stored configuration").

`CURRENT_SCHEMA_VERSION` is what every newly-created `Snapshot` is
stamped with. `SUPPORTED_SCHEMA_VERSIONS` is the set `apply_snapshot()`
accepts -- a snapshot stamped with a version outside this set is rejected
cleanly (`UnsupportedSchemaVersionError`), never silently interpreted.
When a second schema version is ever introduced, a version-specific
migration function is added here and dispatched by version -- this
module is deliberately the one place that dispatch lives, never
scattered across `snapshots.py`.

`SUPPORTED_DOMAINS` is the closed vocabulary of configuration domain
keys a snapshot's `included_domains`/`payload` may name --
`docs/ADR/0013-...`'s own "Decision 1" table: exactly one domain is
implemented in this phase (`crm.pipelines`); every other name is
rejected, not silently ignored.

`validate_payload_shape()` checks structure only (types, required keys,
bounded lengths) -- it never validates business rules specific to one
domain (e.g. "a pipeline needs at least one stage"), which stays in
`product/templates/snapshots.py`'s own domain-specific export/apply
functions, mirroring `product/websites/content_blocks.py`'s own
"structural validation lives with the schema, business rules live with
the caller" split.
"""

from __future__ import annotations

import json

from product.templates.errors import TemplatesValidationError
from product.templates.models import MAX_PAYLOAD_BYTES

CURRENT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

DOMAIN_CRM_PIPELINES = "crm.pipelines"
SUPPORTED_DOMAINS = (DOMAIN_CRM_PIPELINES,)

_MAX_NAME_LENGTH = 255
_MAX_STAGES_PER_PIPELINE = 100
_MAX_PIPELINES_PER_SNAPSHOT = 100


def validate_schema_version(schema_version: int) -> None:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise TemplatesValidationError(
            f"schema_version {schema_version!r} is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})."
        )


def validate_domains(domains: list[str]) -> list[str]:
    if not isinstance(domains, list) or not domains:
        raise TemplatesValidationError("domains must be a non-empty list.")
    if len(domains) != len(set(domains)):
        raise TemplatesValidationError("domains must not contain duplicates.")
    unsupported = [d for d in domains if d not in SUPPORTED_DOMAINS]
    if unsupported:
        raise TemplatesValidationError(
            f"unsupported domain(s) {unsupported!r} (supported: {list(SUPPORTED_DOMAINS)})."
        )
    return domains


def _validate_pipeline_entry(entry: object) -> None:
    if not isinstance(entry, dict):
        raise TemplatesValidationError("each crm.pipelines entry must be an object.")
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > _MAX_NAME_LENGTH:
        raise TemplatesValidationError("each pipeline entry needs a valid 'name'.")
    if not isinstance(entry.get("is_default"), bool):
        raise TemplatesValidationError("each pipeline entry needs a boolean 'is_default'.")
    stages = entry.get("stages")
    if not isinstance(stages, list) or len(stages) > _MAX_STAGES_PER_PIPELINE:
        raise TemplatesValidationError(
            f"each pipeline entry needs a 'stages' list of at most "
            f"{_MAX_STAGES_PER_PIPELINE} entries."
        )
    for stage in stages:
        if not isinstance(stage, dict):
            raise TemplatesValidationError("each stage entry must be an object.")
        stage_name = stage.get("name")
        if (
            not isinstance(stage_name, str)
            or not stage_name.strip()
            or len(stage_name) > _MAX_NAME_LENGTH
        ):
            raise TemplatesValidationError("each stage entry needs a valid 'name'.")
        if not isinstance(stage.get("position"), int) or isinstance(stage.get("position"), bool):
            raise TemplatesValidationError("each stage entry needs an integer 'position'.")
        if not isinstance(stage.get("is_won"), bool) or not isinstance(stage.get("is_lost"), bool):
            raise TemplatesValidationError("each stage entry needs boolean 'is_won'/'is_lost'.")


def validate_payload_shape(schema_version: int, domains: list[str], payload: dict) -> None:
    """Structural validation only (module docstring). Raises
    `TemplatesValidationError` on any shape violation, including an
    oversized serialized payload (defense in depth alongside the
    database's own `ck_templates_snapshots_payload_size` -- validated
    here too so a caller gets a clean 400 rather than discovering the
    limit via a database `IntegrityError`)."""
    validate_schema_version(schema_version)
    validate_domains(domains)
    if not isinstance(payload, dict) or set(payload.keys()) != set(domains):
        raise TemplatesValidationError(
            "payload top-level keys must match included_domains exactly."
        )

    serialized_size = len(json.dumps(payload).encode("utf-8"))
    if serialized_size > MAX_PAYLOAD_BYTES:
        raise TemplatesValidationError(
            f"payload exceeds the maximum size of {MAX_PAYLOAD_BYTES} bytes."
        )

    if DOMAIN_CRM_PIPELINES in payload:
        pipelines = payload[DOMAIN_CRM_PIPELINES]
        if not isinstance(pipelines, list) or len(pipelines) > _MAX_PIPELINES_PER_SNAPSHOT:
            raise TemplatesValidationError(
                f"'{DOMAIN_CRM_PIPELINES}' must be a list of at most "
                f"{_MAX_PIPELINES_PER_SNAPSHOT} entries."
            )
        for entry in pipelines:
            _validate_pipeline_entry(entry)


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "DOMAIN_CRM_PIPELINES",
    "SUPPORTED_DOMAINS",
    "SUPPORTED_SCHEMA_VERSIONS",
    "validate_domains",
    "validate_payload_shape",
    "validate_schema_version",
]
