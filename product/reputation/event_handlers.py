"""Reacts to events published by other modules -- never by importing
them, only by `product.foundation.events.subscribe()` on the plain event
type string (`docs/ARCHITECTURE.md` section 2.2's "module needing another
module's capability reacts via the event dispatcher" path).

**`agency.role_provisioned`** (published by `product/agency/roles.py`):
grants this module's own `reputation.review_request`/`reputation.review`
permissions to the newly provisioned role. `owner`: full lifecycle
control, including `cancel` (review_request) -- cancelling an in-flight
review request is judged the same higher-risk-than-ordinary-CRUD tier
`product/websites/event_handlers.py`'s own module docstring reserves for
`delete`, so it is owner-only. `member`: create/read on both resources,
plus `respond` (posting a response to a review is an ordinary day-to-day
action, not a destructive one) -- never `cancel`.

**`appointments.appointment.completed`** (docs/ROADMAP.md Phase 23
"Customer Lifecycle Loop," published by `product/appointments/booking.py
::staff_complete_appointment()`) -- automatically creates a review
request for the appointment's own contact, reusing
`product.reputation.review_requests.create_review_request()` **entirely
unchanged**, exactly as the roadmap's own scope requires. This is a
structurally different edge than the `product.automation <->
product.reputation` one `docs/ADR/0010-...`'s own "Deferred: Automation
Integration" section declines to grant: subscribing to a plain event-type
string requires no import of `product.appointments` at all (the identical
"subscribe by string, never import" pattern `product.automation` already
uses for its own cross-domain triggers) -- `product.reputation` still
imports nothing beyond `product.crm` (`docs/ADR/0010-...`), and
`pyproject.toml`'s existing "Reputation does not depend on any product
module except CRM" contract needs no change.

`create_review_request()` requires a real, authorized `actor_user_id` --
it was never designed for a system/anonymous caller. The event's own
payload carries the completing staff member's `actor_user_id` for exactly
this reason (`product/appointments/booking.py`'s own module docstring
explains why this is the one event in the product whose payload names an
actor). Both `owner` and `member` already hold
`reputation.review_request:create` by default (this same file's own
`_OWNER_GRANTS`/`_MEMBER_GRANTS` above) -- the ordinary case needs no new
grant. A denial, a contact with no email on file, or any other real
`create_review_request()` failure is caught and audited here, **never**
re-raised: `publish()` calls every subscriber synchronously, in the
publisher's own call stack (`product/foundation/events.py`'s own
docstring), so an unguarded exception here would turn a successful
appointment-completion call into a 500 for a mutation that already
committed -- the identical "one subscriber's failure must never abort the
triggering caller" discipline `product/automation/dispatcher.py
::_handle_event()` already establishes for its own per-workflow loop.
"""

from __future__ import annotations

import uuid

from core.audit_log import ActorType, AuditOutcome, record
from core.rbac import get_role

from product.foundation.events import Event, subscribe
from product.reputation.permissions import REVIEW_REQUEST_RESOURCE, REVIEW_RESOURCE, grant_to_role
from product.reputation.review_requests import create_review_request

_OWNER_ROLE_NAME = "owner"
_MEMBER_ROLE_NAME = "member"

_OWNER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (REVIEW_REQUEST_RESOURCE, ("create", "read", "cancel")),
    (REVIEW_RESOURCE, ("create", "read", "respond")),
)
_MEMBER_GRANTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (REVIEW_REQUEST_RESOURCE, ("create", "read")),
    (REVIEW_RESOURCE, ("create", "read", "respond")),
)


def _handle_agency_role_provisioned(event: Event) -> None:
    role_name = event.payload.get("role_name")
    if role_name not in (_OWNER_ROLE_NAME, _MEMBER_ROLE_NAME):
        return
    tenant_id = uuid.UUID(event.tenant_id)
    role_id = uuid.UUID(str(event.payload["role_id"]))
    role = get_role(tenant_id, role_id)
    grants = _OWNER_GRANTS if role_name == _OWNER_ROLE_NAME else _MEMBER_GRANTS
    for resource, actions in grants:
        grant_to_role(tenant_id, role, resource=resource, actions=actions)


subscribe("agency.role_provisioned", _handle_agency_role_provisioned)


def _handle_appointment_completed(event: Event) -> None:
    tenant_id = uuid.UUID(event.tenant_id)
    contact_id_raw = event.payload.get("contact_id")
    actor_user_id_raw = event.payload.get("actor_user_id")
    if not contact_id_raw or not actor_user_id_raw:
        # No contact on the appointment, or (should never happen for a
        # real `.completed` event) no actor -- nothing to request a
        # review from/as. Not an error: an appointment with no linked
        # contact is a legitimate, pre-existing state.
        return
    try:
        create_review_request(
            uuid.UUID(str(actor_user_id_raw)), tenant_id, uuid.UUID(str(contact_id_raw))
        )
    except Exception as exc:  # noqa: BLE001 -- see module docstring: this
        # handler must NEVER let an exception escape into the publisher's
        # own call stack, regardless of cause. The ordinary, expected
        # denial/lookup/validation shapes
        # (`ReputationAccessDeniedError`/`ReputationReferenceNotFoundError`/
        # `ReputationValidationError`) are not the only ones possible --
        # `create_review_request()` can also raise
        # `core.email.errors.EmailConfigurationError` (e.g. `SMTP_HOST`
        # unset) straight out of `get_email_config()`, *before* its own
        # internal send-failure handling ever gets a chance to catch it --
        # a genuine, real environment/configuration problem, not a
        # caller-input error, but just as much "not this caller's fault."
        # Mirrors `product/automation/dispatcher.py::_run_workflow()`'s
        # own identical, already-justified broad `except Exception` for
        # the same "one subscriber's failure must never abort the
        # triggering caller" reasoning -- audited here exactly as broadly
        # as it is caught, so the failure is visible to an operator
        # either way.
        record(
            tenant_id=tenant_id,
            actor_type=ActorType.SYSTEM,
            action="reputation.review_request.auto_create_failed",
            resource_type="reputation.review_request",
            resource_id=str(contact_id_raw),
            outcome=AuditOutcome.FAILURE,
            metadata={"reason": type(exc).__name__},
        )


subscribe("appointments.appointment.completed", _handle_appointment_completed)
