"""The closed **production** AI capability vocabulary (docs/ROADMAP.md
Phase 9.4).

Phase 9.1-9.3 defined five tools. This module answers a different, and
much narrower, question than "which tools exist": **which tools a tenant
may ever be granted in production**. Those are not the same set, and
conflating them is exactly how a tool written for one bounded purpose
quietly becomes a general-purpose data egress path.

`PRODUCTION_CAPABILITIES` below names exactly one tool today --
`ai.crm.qualify_lead`. It was chosen as the smallest capability that can
prove the whole production path end to end (Phase 9.4's own stated
purpose is to prove the Control Plane production path, not to widen AI
breadth):

- its payload is a single `contact_id` -- an identifier, never a copied
  record, so nothing PII-shaped needs to travel to reach it;
- the handler fetches the contact itself, *after* `invoke_tool()` has
  already enforced RBAC, autonomy tier, and Data Authorization;
- its RBAC gate reuses `crm.contact`/`read`, so it can never exceed what
  the invoking actor could already read directly;
- it is `autonomy_tier=0` and `side_effect="read_only"` -- an advisory
  read, nothing to undo, nothing to make idempotent;
- its output is bounded by `product/ai/provider.py`'s own
  `MAX_OUTPUT_CHARS` clamp, structurally rather than by convention.

`ai.telephony.receptionist_advice` is deliberately **excluded**, and not
merely "not yet added": its payload requires a caller-supplied raw
`transcript` string. That is free-text call content, which is precisely
the kind of payload this phase is supposed to keep out of persisted and
durable state. Adding it is a separate decision with its own review, not
an increment.

A capability being *in* this vocabulary grants nothing by itself. It
only makes the capability **eligible** to be named in a tenant's own
persisted policy (`product/ai/policy.py`); an eligible-but-unapproved
capability is denied by Data Authorization's own default-deny path like
any other.
"""

from __future__ import annotations

from product.ai.errors import AIValidationError
from product.ai.tools.lead_qualification import TOOL_KEY as QUALIFY_LEAD_TOOL_KEY

#: The one capability approved for production execution today. Widening
#: this set is a reviewed decision -- see this module's own docstring.
PRODUCTION_CAPABILITIES = frozenset({QUALIFY_LEAD_TOOL_KEY})

#: The `resource_type` each production capability reads, used to build the
#: `DataAuthorizationRequest` for it. Kept beside the capability list so a
#: capability can never be approved without its resource type being
#: declared in the same reviewed change.
PRODUCTION_CAPABILITY_RESOURCE_TYPES: dict[str, str] = {
    QUALIFY_LEAD_TOOL_KEY: "crm.contact",
}


def validate_capability(capability: str) -> None:
    """Raise `AIValidationError` unless `capability` is in the closed
    production vocabulary. The one chokepoint every policy mutation runs
    through, so an unknown or misspelled capability can never be
    persisted into a tenant's approved list."""
    if capability not in PRODUCTION_CAPABILITIES:
        raise AIValidationError(
            f"{capability!r} is not an approved production AI capability "
            f"(approved: {sorted(PRODUCTION_CAPABILITIES)})."
        )


def resource_type_for(capability: str) -> str:
    validate_capability(capability)
    return PRODUCTION_CAPABILITY_RESOURCE_TYPES[capability]


__all__ = [
    "PRODUCTION_CAPABILITIES",
    "PRODUCTION_CAPABILITY_RESOURCE_TYPES",
    "resource_type_for",
    "validate_capability",
]
