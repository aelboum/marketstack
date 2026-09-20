"""Product-owned exceptions for `product/telephony/` (docs/ROADMAP.md
Phase 8). Mirrors `product/appointments/errors.py`/`product/crm/errors.py`'s
own discipline exactly.
"""

from __future__ import annotations

import uuid


class TelephonyAccessDeniedError(Exception):
    """Raised by every `product/telephony/*.py` service function when
    `actor_user_id` does not hold the required `(resource, action)`
    capability at `tenant_id` -- see `product/telephony/permissions.py
    ::require()`."""

    def __init__(
        self, actor_user_id: uuid.UUID, tenant_id: uuid.UUID, *, resource: str, action: str
    ) -> None:
        self.actor_user_id = actor_user_id
        self.tenant_id = tenant_id
        self.resource = resource
        self.action = action
        super().__init__(
            f"{actor_user_id} is not authorized for {action!r} on {resource!r} "
            f"in tenant {tenant_id}."
        )


class TelephonyReferenceNotFoundError(Exception):
    """Raised when a caller-supplied related-entity id (a phone number,
    call, or routing-target user) does not resolve to a real, in-tenant
    row. Mapped to the same non-enumerating 404 as
    `TelephonyAccessDeniedError` at the API layer."""

    def __init__(self, entity: str, entity_id: object) -> None:
        self.entity = entity
        self.entity_id = entity_id
        super().__init__(f"{entity} {entity_id} not found in this tenant.")


class TelephonyValidationError(ValueError):
    """Raised for a caller-input shape error this module validates itself
    (an invalid E.164 number, an empty routing-target list, a malformed
    provider event payload) -- a 400-shaped client error, never an
    authorization or lookup failure."""


class TelephonyProviderError(RuntimeError):
    """Raised by a `TelephonyProvider`/`ObjectStorage` implementation on
    failure -- mirrors `product.conversations.sms.SmsProviderError`'s own
    normalized-error discipline (never a raw transport/SDK exception)."""


class TelephonyProviderNotConfiguredError(Exception):
    """Raised when a provider-dependent operation is attempted with no
    real provider configured -- see `product/telephony/provider.py`'s own
    module docstring: there is no default `TelephonyProvider`, mirroring
    `product/conversations/sms.py::send_sms_message()`'s identical
    design. Distinct from `TelephonyProviderError` (a real provider that
    failed) -- this is "no provider was even supplied.\""""


class TelephonyWebhookSignatureInvalidError(Exception):
    """Raised when an inbound provider event's signature fails
    verification (`TelephonyProvider.verify_webhook_signature()`) -- the
    event is rejected before any database read/write, per
    `docs/INTEGRATIONS.md` "Webhook Security": an unverified webhook is
    rejected, not processed."""


class TelephonyUnknownNumberError(Exception):
    """Raised when an inbound provider event's `to_number` does not
    resolve to any provisioned `PhoneNumber` -- deliberately never
    inferring or trusting a tenant id supplied directly by the event
    payload itself (this phase's own explicit requirement)."""


class TelephonyInvalidStateTransitionError(Exception):
    """Raised when a call-state transition is attempted from a status
    that does not permit it (e.g. a second "answered" event after the
    call already `completed`) -- see `product/telephony/calls.py`'s own
    module docstring for the full, explicit transition table. A duplicate
    delivery of the *same* transition is idempotent (a no-op, not this
    error) -- see that module's own idempotency handling."""

    def __init__(self, call_id: uuid.UUID, *, current_status: str, requested_status: str) -> None:
        self.call_id = call_id
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            f"call {call_id} cannot transition from {current_status!r} to {requested_status!r}."
        )
