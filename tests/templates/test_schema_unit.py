"""`product/templates/schema.py`: pure, no-database validators
(docs/ROADMAP.md Phase 14). Not marked `integration` -- runs in the
default `pytest` invocation.
"""

from __future__ import annotations

import pytest
from product.templates.errors import TemplatesValidationError
from product.templates.schema import (
    CURRENT_SCHEMA_VERSION,
    DOMAIN_CRM_PIPELINES,
    validate_domains,
    validate_payload_shape,
    validate_schema_version,
)


def test_validate_schema_version_accepts_supported() -> None:
    validate_schema_version(1)


def test_validate_schema_version_rejects_unsupported() -> None:
    with pytest.raises(TemplatesValidationError):
        validate_schema_version(2)


def test_validate_schema_version_rejects_zero_and_negative() -> None:
    with pytest.raises(TemplatesValidationError):
        validate_schema_version(0)
    with pytest.raises(TemplatesValidationError):
        validate_schema_version(-1)


def test_validate_domains_rejects_empty() -> None:
    with pytest.raises(TemplatesValidationError):
        validate_domains([])


def test_validate_domains_rejects_duplicates() -> None:
    with pytest.raises(TemplatesValidationError):
        validate_domains([DOMAIN_CRM_PIPELINES, DOMAIN_CRM_PIPELINES])


def test_validate_domains_rejects_unsupported() -> None:
    with pytest.raises(TemplatesValidationError):
        validate_domains(["marketing.forms"])


def test_validate_domains_accepts_supported() -> None:
    assert validate_domains([DOMAIN_CRM_PIPELINES]) == [DOMAIN_CRM_PIPELINES]


def _valid_pipeline_payload() -> dict:
    return {
        DOMAIN_CRM_PIPELINES: [
            {
                "name": "Sales",
                "is_default": True,
                "stages": [
                    {"name": "Open", "position": 0, "is_won": False, "is_lost": False},
                    {"name": "Won", "position": 1, "is_won": True, "is_lost": False},
                ],
            }
        ]
    }


def test_validate_payload_shape_accepts_valid_payload() -> None:
    validate_payload_shape(
        CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], _valid_pipeline_payload()
    )


def test_validate_payload_shape_rejects_mismatched_top_level_keys() -> None:
    payload = _valid_pipeline_payload()
    payload["unexpected.domain"] = []
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)


def test_validate_payload_shape_rejects_missing_pipeline_name() -> None:
    payload = {DOMAIN_CRM_PIPELINES: [{"is_default": False, "stages": []}]}
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)


def test_validate_payload_shape_rejects_non_boolean_is_default() -> None:
    payload = {DOMAIN_CRM_PIPELINES: [{"name": "Sales", "is_default": "yes", "stages": []}]}
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)


def test_validate_payload_shape_rejects_stage_with_bad_position_type() -> None:
    payload = {
        DOMAIN_CRM_PIPELINES: [
            {
                "name": "Sales",
                "is_default": False,
                "stages": [{"name": "Open", "position": "0", "is_won": False, "is_lost": False}],
            }
        ]
    }
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)


def test_validate_payload_shape_rejects_stage_position_as_bool() -> None:
    """`isinstance(True, int)` is `True` in Python -- must be explicitly
    excluded, mirroring the same guard already applied elsewhere in this
    codebase (e.g. `product/reputation/reviews.py::_validate_rating()`)."""
    payload = {
        DOMAIN_CRM_PIPELINES: [
            {
                "name": "Sales",
                "is_default": False,
                "stages": [{"name": "Open", "position": True, "is_won": False, "is_lost": False}],
            }
        ]
    }
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)


def test_validate_payload_shape_rejects_oversized_payload() -> None:
    payload = {
        DOMAIN_CRM_PIPELINES: [
            {
                "name": "Sales",
                "is_default": False,
                "stages": [
                    {"name": f"Stage {i}", "position": i, "is_won": False, "is_lost": False}
                    for i in range(100)
                ],
            }
            for _ in range(50)
        ]
    }
    with pytest.raises(TemplatesValidationError):
        validate_payload_shape(CURRENT_SCHEMA_VERSION, [DOMAIN_CRM_PIPELINES], payload)
