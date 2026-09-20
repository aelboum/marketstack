"""Shared pagination bounds for every `product/marketing/*.py` list
endpoint -- identical constants/logic to `product/crm/pagination.py`/
`product/conversations/pagination.py`, but NOT imported from either:
`product.marketing` importing `product.crm.pagination` would work
mechanically now that
`docs/ADR/0005-marketing-and-appointments-depend-on-crm.md`
permits a `product.marketing -> product.crm` dependency edge, but
pagination bounds are an API/service-layer convention, not CRM-domain
state -- tying this ordinary utility to that one narrow, CRM-specific
dependency channel would blur why it exists. `product/conversations
/pagination.py`'s own module docstring already made and recorded this
exact judgment call (duplicate a tiny, genuinely shared utility rather
than introduce or ride a cross-module dependency for it) when
`product.conversations` had no CRM dependency to reuse at all; the
reasoning here is the same, even though the mechanical option is now
different. Revisit if a third/fourth module needs the identical bounds
and the duplication starts to feel real rather than theoretical --
promoting to `product/foundation/` remains the right move at that point,
not leaning on whichever module happens to already have a sanctioned
import path.
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
