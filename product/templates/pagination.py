"""Shared pagination bounds for every `product/templates/*.py` list
endpoint -- identical constants/logic to `product/reputation/pagination.py`,
but NOT imported from it: the same "duplicate a tiny, genuinely shared
utility rather than ride a cross-module dependency for it" judgment call
those modules already made and recorded, applied here for the identical
reason.
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
