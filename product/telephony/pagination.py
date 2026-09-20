"""Shared pagination bounds for every `product/telephony/*.py` list
endpoint -- identical constants/logic to `product/appointments/pagination.py`/
`product/marketing/pagination.py`, but NOT imported from either: the same
"duplicate a tiny, genuinely shared utility rather than introduce a
cross-module dependency for it" judgment call those modules already made
and recorded, applied here for the identical reason.
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
