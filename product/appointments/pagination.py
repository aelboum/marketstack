"""Shared pagination bounds for every `product/appointments/*.py` list
endpoint -- identical constants/logic to `product/crm/pagination.py`/
`product/conversations/pagination.py`/`product/marketing/pagination.py`,
but NOT imported from any of them: this is the same "duplicate a tiny,
genuinely shared utility rather than introduce or ride a cross-module
dependency for it" judgment call `product/conversations/pagination.py`
and `product/marketing/pagination.py` already made and recorded, applied
here for the identical reason (pagination bounds are an API/service-layer
convention, not CRM-domain state, so `docs/ADR/0005-...`'s
`product.appointments -> product.crm` dependency edge is not the right
channel for it either, even though it would work mechanically).
"""

from __future__ import annotations

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def clamp_limit(limit: int) -> int:
    """Coerce a caller-supplied page size into `[1, MAX_PAGE_SIZE]` --
    never trust a caller-supplied limit unbounded, and never allow zero
    or negative (which some ORMs/drivers treat as "no limit")."""
    if limit < 1:
        return 1
    return min(limit, MAX_PAGE_SIZE)
