"""The approved Phase 27.0 human-destination boundary (docs/ROADMAP.md
Phase 27.0 -- "Twilio Telephony Foundation").

**Exactly one trusted, tenant-configured destination per tenant.** No
ordered list, no queue, no department, no per-phone-number variant, no
global default. If a tenant has configured none, `resolve_human_destination()`
returns `None` -- the caller (`product/telephony/transfer.py`) treats that
as "transfer unavailable," never guesses a number, never falls back to the
caller's own number, and never falls back to a tenant owner's personal
profile.

**Provider-neutral by construction.** `HumanDestination` is the same
`{kind, value}` shape regardless of which `TelephonyProvider` adapter is
active -- a future Telnyx or SIP/PBX adapter consumes the identical
logical value. `kind` is `DESTINATION_KIND_E164`
(`product/telephony/models.py`) today; `SIP URI` remains a documented,
anticipated future kind this type does not yet implement (this phase's
own "do not implement SIP URI handling now" instruction) -- adding it
later is a matter of adding a second `kind` value here and to
`HumanTransferDestination`'s own CHECK constraint, not a redesign of this
module's shape.

**Never derived from caller input, AI output, or provider webhook data.**
Every function here takes an already-authenticated `actor_user_id`/
`tenant_id` and reads/writes exactly one RLS-scoped row
(`HumanTransferDestination`) -- there is no code path anywhere in this
module that accepts a phone number from an inbound call, a webhook
payload, or an AI tool's own decision output.

**Reuses the existing, already country-neutral E.164 validator.**
`product.foundation.values.normalize_phone_number()` (already used by
`product/crm/contacts.py` for contact phone numbers) is the one
normalization/validation path -- no Dutch-specific or otherwise
country-specific validator is introduced here, preserving this
architecture's explicit global-usability requirement.

**Authorization** goes through the existing
`product/telephony/permissions.py::require()` chokepoint, gated by the
new `HUMAN_DESTINATION_RESOURCE` -- no second authorization mechanism.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from core.audit_log import ActorType, AuditOutcome, record
from infra.db import select, tenant_session_scope

from product.foundation.values import InvalidPhoneNumberError, normalize_phone_number
from product.telephony.errors import TelephonyValidationError
from product.telephony.models import DESTINATION_KIND_E164, HumanTransferDestination
from product.telephony.permissions import HUMAN_DESTINATION_RESOURCE, require


@dataclass(frozen=True, slots=True)
class HumanDestination:
    """The provider-neutral logical destination a `TelephonyProvider`
    adapter dials for an attended transfer. `kind` is always
    `DESTINATION_KIND_E164` today; `value` is always a normalized E.164
    string in that case."""

    kind: str
    value: str


def set_human_transfer_destination(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, e164_value: str
) -> HumanDestination:
    """Create or replace `tenant_id`'s own single trusted human-transfer
    destination. `e164_value` is normalized/validated via the existing,
    country-neutral `product.foundation.values.normalize_phone_number()`
    -- a malformed value raises `TelephonyValidationError` (this module's
    own existing "caller-input shape error" convention), never silently
    coerced or truncated."""
    require(actor_user_id, tenant_id, resource=HUMAN_DESTINATION_RESOURCE, action="update")
    try:
        normalized = str(normalize_phone_number(e164_value))
    except InvalidPhoneNumberError as exc:
        raise TelephonyValidationError(f"not a valid E.164 destination: {e164_value!r}") from exc

    with tenant_session_scope(tenant_id) as session:
        row = session.execute(
            select(HumanTransferDestination).where(HumanTransferDestination.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            row = HumanTransferDestination(
                tenant_id=tenant_id,
                kind=DESTINATION_KIND_E164,
                e164_value=normalized,
            )
            session.add(row)
        else:
            row.e164_value = normalized
        session.flush()
        session.refresh(row)
        destination_id = row.id
        session.expunge(row)

    record(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action="telephony.human_transfer_destination.set",
        resource_type="telephony.human_transfer_destination",
        resource_id=str(destination_id),
        outcome=AuditOutcome.SUCCESS,
        # Identifier only -- never the destination number itself, mirroring
        # product/telephony/numbers.py::provision_phone_number()'s own
        # PII/audit discipline.
    )
    return HumanDestination(kind=DESTINATION_KIND_E164, value=normalized)


def get_human_transfer_destination(
    actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> HumanDestination | None:
    """Read `tenant_id`'s own configured destination, or `None` if none
    has been configured -- never an error, since "no destination
    configured" is a normal, deterministic, expected state (see
    `product/telephony/transfer.py`'s own "transfer unavailable"
    handling)."""
    require(actor_user_id, tenant_id, resource=HUMAN_DESTINATION_RESOURCE, action="read")
    return resolve_human_destination(tenant_id)


def resolve_human_destination(tenant_id: uuid.UUID) -> HumanDestination | None:
    """The trusted, server-side-only resolution path
    `product/telephony/transfer.py::initiate_transfer()` calls directly --
    deliberately takes no `actor_user_id` and performs no authorization
    check of its own, because the call initiating a transfer is an
    internal system decision (the AI receptionist's own `escalate`
    decision, already authorized upstream by Phase 27.1/27.2's own
    boundaries), never a caller- or AI-output-driven lookup a human actor
    requested. Mirrors `product/telephony/calls.py::_resolve_phone_number()`'s
    own "internal, no separate RBAC gate" shape for the identical reason:
    this is not a new capability a role can be granted or denied --
    it is which tenant's own already-established row applies."""
    with tenant_session_scope(tenant_id) as session:
        row = session.execute(
            select(HumanTransferDestination).where(HumanTransferDestination.tenant_id == tenant_id)
        ).scalar_one_or_none()
        if row is None:
            return None
        return HumanDestination(kind=row.kind, value=row.e164_value)


__all__ = [
    "HumanDestination",
    "get_human_transfer_destination",
    "resolve_human_destination",
    "set_human_transfer_destination",
]
