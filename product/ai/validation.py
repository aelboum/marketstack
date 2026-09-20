"""Shared payload-validation helpers for `product/ai/tools/*.py` --
identical "duplicate a tiny, genuinely shared utility rather than ride a
cross-module dependency for it" judgment call `product/appointments
/pagination.py`/`product/telephony/pagination.py` already made and
recorded, applied here to input validation instead of pagination bounds.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from product.ai.errors import AIValidationError

MAX_STRING_FIELD_CHARS = 4_000


def require_uuid(payload: Mapping[str, object], field_name: str) -> uuid.UUID:
    raw = payload.get(field_name)
    if not isinstance(raw, str):
        raise AIValidationError(f"payload.{field_name} must be a string.")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise AIValidationError(f"payload.{field_name} must be a valid UUID.") from exc


def require_bounded_string(payload: Mapping[str, object], field_name: str) -> str:
    raw = payload.get(field_name)
    if not isinstance(raw, str) or not raw:
        raise AIValidationError(f"payload.{field_name} must be a non-empty string.")
    if len(raw) > MAX_STRING_FIELD_CHARS:
        raise AIValidationError(
            f"payload.{field_name} exceeds {MAX_STRING_FIELD_CHARS} characters."
        )
    return raw


__all__ = ["MAX_STRING_FIELD_CHARS", "require_bounded_string", "require_uuid"]
