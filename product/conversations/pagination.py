"""Shared pagination bounds for every `product/conversations/*.py` list
endpoint -- identical constants/logic to `product/crm/pagination.py`, but
NOT imported from there: `product.conversations` importing
`product.crm.pagination` would cross the sibling-module independence
boundary this repository's own import-linter contract enforces
(`docs/ARCHITECTURE.md` section 2.2), the same rule that already forced
`product/crm/event_handlers.py` to react to `product.agency`'s events
instead of importing it directly. Promoting this one tiny, genuinely
shared utility to `product/foundation/` was considered and rejected for
now -- two nearly-identical eight-line copies is a smaller, more honest
cost than a cross-module dependency or a foundation promotion for
something this narrow; revisit if a third module needs the identical
bounds and the duplication starts to feel real rather than theoretical.
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
