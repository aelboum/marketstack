"""Shared pagination bounds for `product/automation/*.py` list endpoints
-- identical constants/logic to every other module's own copy
(`product/telephony/pagination.py`'s own docstring records the same
"duplicate a tiny, genuinely shared utility" judgment call, applied here
for the identical reason).
"""

from __future__ import annotations

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    return min(limit, MAX_PAGE_SIZE)
