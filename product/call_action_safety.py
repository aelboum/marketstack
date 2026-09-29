"""Phase 27.2 ("Call-Initiated Action Safety") -- the one integration
layer that lets a live phone turn (`product/telephony/call_session.py`)
safely invoke an existing Phase 26 business capability
(`product/ai/invocation.py::invoke_product_ai_tool()`/
`execute_approved_ai_tool()`), for exactly the narrow set of capabilities
this module explicitly allowlists.

**Why this lives here, outside `product.ai`, `product.telephony`, and
`product.appointments`.** The import-linter contracts forbid
`product.ai -> product.appointments` (`"AI does not depend on any product
module except CRM, Conversations, or Telephony"`), `product.appointments
-> product.ai`/`-> product.telephony` (`"Marketing and Appointments do not
depend on any product module except CRM"`), and `product.telephony ->
product.ai` (`"AI may depend on Telephony, never Telephony on AI"` --
`product/telephony/call_session.py`'s own module docstring already states
this explicitly). This module genuinely needs all three at once: the
call/turn/actor state from `product.telephony`, the audited invocation
path from `product.ai`, and the one phone-safe capability's own real
implementation in `product.appointments`. No pair of those three packages
can perform this wiring itself -- exactly the situation
`product/action_registry_composition.py`'s own module docstring already
names and solves the identical way: a third, neutral module, directly
under `product`, allowed to import all of them, whose only job is this
one explicit bridge. Never a second tool registry, a second executor, or
a second approval engine -- every real authorization/audit/approval
decision below is made by the existing `control_plane`/`core` functions
this module calls unmodified.

**The caller is never the authenticated actor.** Every call into Phase 26
below passes `identity.receptionist_actor_user_id` (Phase 27.1's own
tenant-scoped, zero-standing-until-granted `AiReceptionistActor`) as
`actor_user_id` -- never anything derived from caller-supplied speech,
never a value read out of `payload`. `identity.tenant_id` -- fixed at
`CallSession` construction from the trusted inbound DID
(`product/telephony/receptionist.py`'s own docstring) -- is the only
tenant a call in this process can ever act as; nothing in this module
accepts a caller- or payload-supplied tenant id.

**The phone-safe capability boundary is a real allowlist, not an
inference from `autonomy_tier`.** `PHONE_SAFE_CAPABILITIES` below names
every tool key this module will ever execute for an unauthenticated
caller -- currently exactly one, read-only appointment availability
(`product/appointments/availability.py::compute_available_slots()`,
wrapped, never modified). A tool key not in this set is refused before
`invoke_product_ai_tool()` is ever called, however tempting it might be to
reuse an existing, otherwise-safe-looking, tier-0 tool. This module never
grows that allowlist to include contact lookup, contact creation/update,
or appointment booking -- `docs/ADR/0018-inbound-phone-caller-contact
-trust-boundary.md` is the reason: an unauthenticated phone caller must
never cause an existing CRM contact to be matched/updated, and this
module's own availability tool never touches `product.crm.contacts` or
`product/appointments/booking.py::book_appointment()` at all -- there is
no code path here that could reach either.

**Data Authorization does not apply to the one capability registered
here.** `compute_available_slots()` never sends anything to an external
AI/LLM provider -- it is a plain, tenant-scoped database read -- so its
`ToolDefinition` below declares `requires_data_authorization=False`
honestly, rather than declaring `True` and then needing
`product/ai/capabilities.py::PRODUCTION_CAPABILITIES` (a closed vocabulary
this module deliberately does not touch) to be extended just to make a
non-LLM capability satisfy a gate that was never about it. RBAC
(`core.rbac.can()`, via the tool's own `required_resource`/
`required_action`) remains the only, unweakened gate --
`ensure_phone_safe_permissions()` below is the one place this module
grants that permission, idempotently, to a tenant's own receptionist
role, mirroring `product/appointments/permissions.py::grant_to_role()`'s
own existing discipline exactly.

**`execute_phone_action()` never accepts a caller-supplied `ToolRegistry`**
(Security Checkpoint, Phase 27.2 -- closing a HIGH finding). An earlier
revision took an optional `registry` parameter, defaulting to
`build_phone_registry()` when omitted. That parameter was a real
authorization bypass: `PHONE_SAFE_CAPABILITIES` only ever closes the set
of tool-key *strings*, never the binding from a key to its actual
`ToolDefinition` -- a caller supplying `registry=<a registry rebinding
APPOINTMENT_AVAILABILITY_TOOL_KEY to an attacker-authored handler,
resource, action, or autonomy_tier>` would have had that substituted
definition executed as the receptionist actor, with RBAC/tier/Data
Authorization all evaluated against whatever the attacker's own
`ToolDefinition` declared, not the real capability. The fix is structural,
not a check: this function now *always* resolves the tool through its own
internal call to `build_phone_registry()` -- there is no parameter, no
environment variable, and no runtime flag through which any caller,
trusted or not, can substitute a different registry. `build_phone_registry()`
itself remains the one, unchanged, public trusted-composition function
(tests that need to exercise this module's *generic* tier-handling logic
against a second, deliberately-distinct capability do so by monkeypatching
`product.call_action_safety.build_phone_registry` itself -- a test-harness
capability with no runtime input path, never a parameter an untrusted
caller could reach).

**Idempotency reuses `core.idempotency` unmodified** -- no second store.
`begin_idempotent_operation()`/`finalize_idempotent_operation()` (the
two-step primitive, not `run_idempotent()`: `invoke_product_ai_tool()`
opens its own database session internally, so the atomic single-
transaction primitive's own "business_fn must run on the same session as
the reservation" constraint cannot be satisfied here) key on
`(tenant_id, f"telephony.phone_action.{tool_key}",
f"{call_id}.{session_id}.{turn_id}")` -- tenant isolation is the
`IdempotencyRecord`'s own real three-column unique index, not re-derived
by string concatenation; a genuinely new turn always gets a genuinely new
key; a retried delivery of the *same* turn/action replays the stored
result without calling `invoke_product_ai_tool()` a second time. This
deliberately does **not** wrap a tier>=1 action's full
propose-to-approval lifecycle: approval may remain pending indefinitely,
and `core.idempotency`'s own `IDEMPOTENCY_PENDING_TTL_SECONDS` (30s
default) is sized for a synchronous external call, not an unbounded human
decision -- what this module's idempotency covers is the phone *request*
(create-the-proposal-once), never the wait for a human. Once approved,
`control_plane.approvals.execute_approved()`'s own atomic
`"approved" -> "executing"` compare-and-swap (already exactly-once,
unrelated to this module) remains the sole authority over execution.

**Turn-decision timing.** This module decides `attempt` (tier 0) or
`escalate` (tier >= 1) from the tool's own *static* `autonomy_tier` --
known before any execution is attempted -- then drives
`CallSession.apply_decision()` accordingly, matching Phase 27.1's own
closed transition table exactly (`decided -> action_pending -> completed`
for an attempt; `decided -> escalation_pending -> completed` for a
tier>=1 proposal, which is a genuinely correct use of "escalate": the AI
did not attempt to decide this alone, a human must). A pre-execution RBAC
denial is decided as `decline` instead, before `invoke_product_ai_tool()`
is even called. Phase 27.1's own vocabulary is never extended -- no fifth
decision value is added, and an authorization/execution failure that
surfaces *after* a decision has already been committed (an unavoidable,
narrow TOCTOU window, structurally identical to the one
`product/telephony/receptionist.py::ensure_ai_receptionist_actor()`'s own
docstring already accepts for its provisioning race) is reported through
this module's own `PhoneActionOutcome.succeeded`/`error_category`
fields, never by silently rewriting `Turn.decision` after the fact."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import cast

from control_plane.data_authorization import TenantAIDataPolicy
from control_plane.orchestration import (
    DataAuthorizationRequiredError,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionError,
    ToolRegistry,
    UnauthorizedToolInvocationError,
)
from core.audit_log import AuditOutcome
from core.idempotency import (
    IdempotencyStatus,
    begin_idempotent_operation,
    finalize_idempotent_operation,
)
from core.rbac import can as rbac_can
from core.rbac import get_role

from product.ai.invocation import invoke_product_ai_tool
from product.appointments.availability import compute_available_slots
from product.appointments.permissions import CALENDAR_RESOURCE, grant_to_role
from product.telephony.call_session import CallDecision, CallSession, record_turn_audit
from product.telephony.receptionist import AiReceptionistActor

#: The one phone-safe capability this phase implements. Never contact
#: lookup/creation/update, never appointment booking -- see module
#: docstring.
APPOINTMENT_AVAILABILITY_TOOL_KEY = "ai.telephony.appointment_availability"

#: The real, closed allowlist -- checked before `invoke_product_ai_tool()`
#: is ever called, independent of any tool's own `autonomy_tier`.
PHONE_SAFE_CAPABILITIES: frozenset[str] = frozenset({APPOINTMENT_AVAILABILITY_TOOL_KEY})

_AUDIT_ACTION_DECLINED = "telephony.phone_action.declined"
_AUDIT_ACTION_DENIED = "telephony.phone_action.denied"
_AUDIT_ACTION_FAILED = "telephony.phone_action.failed"
_AUDIT_ACTION_SUCCEEDED = "telephony.phone_action.succeeded"
_AUDIT_ACTION_PENDING_APPROVAL = "telephony.phone_action.pending_approval"


def _require_uuid(payload: Mapping[str, object], field_name: str) -> uuid.UUID:
    raw = payload.get(field_name)
    if not isinstance(raw, str):
        raise ValueError(f"payload.{field_name} must be a string.")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValueError(f"payload.{field_name} must be a valid UUID.") from exc


def _require_iso_date(payload: Mapping[str, object], field_name: str) -> date:
    raw = payload.get(field_name)
    if not isinstance(raw, str):
        raise ValueError(f"payload.{field_name} must be a string.")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"payload.{field_name} must be an ISO date (YYYY-MM-DD).") from exc


def _require_int(payload: Mapping[str, object], field_name: str) -> int:
    raw = payload.get(field_name)
    if not isinstance(raw, int) or isinstance(raw, bool):
        raise ValueError(f"payload.{field_name} must be an integer.")
    return raw


async def _availability_handler(
    context: ToolExecutionContext, payload: Mapping[str, object]
) -> dict[str, object]:
    """`context.agent_user_id`/`context.tenant_id` are exactly the
    receptionist actor and the fixed session tenant
    `invoke_product_ai_tool()` was called with below -- never anything a
    caller supplied. `compute_available_slots()` itself performs the real
    `require(..., resource=CALENDAR_RESOURCE, action="read")` RBAC check
    and never creates or modifies a contact or an appointment (it is a
    pure read) -- unmodified, unwrapped in behavior, only its own
    existing signature called."""
    calendar_id = _require_uuid(payload, "calendar_id")
    date_from = _require_iso_date(payload, "date_from")
    date_to = _require_iso_date(payload, "date_to")
    slot_duration_minutes = _require_int(payload, "slot_duration_minutes")

    slots = compute_available_slots(
        context.agent_user_id,
        context.tenant_id,
        calendar_id,
        date_from=date_from,
        date_to=date_to,
        slot_duration_minutes=slot_duration_minutes,
    )
    return {
        "calendar_id": str(calendar_id),
        "slots": [
            {"starts_at": slot.starts_at.isoformat(), "ends_at": slot.ends_at.isoformat()}
            for slot in slots
        ],
    }


def build_phone_registry() -> ToolRegistry:
    """A fresh `ToolRegistry` containing exactly `PHONE_SAFE_CAPABILITIES`
    -- never the process-wide `control_plane.orchestration.default_registry()`,
    never `product/ai/production.py::production_tool_registry()`'s own,
    differently-scoped (vendor-trust, not caller-trust) allowlist. This is
    the one, sole trusted composition point `execute_phone_action()` itself
    calls internally on every invocation -- cheap and side-effect-free to
    call repeatedly, and never taken as a caller-suppliable parameter
    anywhere in this module (module docstring's own "never accepts a
    caller-supplied `ToolRegistry`" section)."""
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            key=APPOINTMENT_AVAILABILITY_TOOL_KEY,
            description=(
                "Read-only appointment availability for one calendar -- safe for an "
                "unauthenticated inbound phone call (docs/ADR/0018-...)."
            ),
            handler=_availability_handler,
            required_scope_type="tenant",
            required_resource=CALENDAR_RESOURCE,
            required_action="read",
            autonomy_tier=0,
            data_classification="tenant_data",
            side_effect="read_only",
            requires_data_authorization=False,
        )
    )
    return registry


def ensure_phone_safe_permissions(actor: AiReceptionistActor) -> None:
    """Idempotently grant `actor`'s own dedicated role exactly the
    permission(s) `PHONE_SAFE_CAPABILITIES` needs today --
    `CALENDAR_RESOURCE`/`read`, nothing else. Mirrors
    `product/appointments/permissions.py::grant_to_role()`'s own existing
    idempotent check-then-grant discipline unchanged; this function
    invents no new permission model and never grants anything beyond what
    this module's own allowlisted capabilities actually require."""
    role = get_role(actor.tenant_id, actor.role_id)
    grant_to_role(actor.tenant_id, role, resource=CALENDAR_RESOURCE, actions=("read",))


def _receptionist_authorized(
    tool: ToolDefinition, *, actor_user_id: uuid.UUID, tenant_id: uuid.UUID
) -> bool:
    """The identical `core.rbac.can()` check `invoke_product_ai_tool()`
    will independently re-run inside `control_plane.orchestration
    ._execute_tool()` -- computed once more, here, purely to decide
    *which* Phase 27.1 decision (`attempt`/`escalate` vs `decline`) to
    commit before any execution is attempted. Never a second
    authorization system: the real, only enforcement remains inside the
    call below."""
    assert tool.required_resource is not None
    assert tool.required_action is not None
    return rbac_can(
        actor_id=actor_user_id,
        tenant_id=tenant_id,
        action=tool.required_action,
        resource=tool.required_resource,
    )


@dataclass(frozen=True, slots=True)
class PhoneActionOutcome:
    """What actually happened when a phone turn attempted
    `tool_key` -- distinct from, and a superset of, Phase 27.1's own
    `Turn.decision` (see module docstring's own "Turn-decision timing"
    section for why the two can diverge on a rare authorization-race
    failure)."""

    turn_id: uuid.UUID
    decision: CallDecision
    succeeded: bool
    replayed: bool
    error_category: str | None = None
    result: dict[str, object] | None = None
    approval_id: str | None = None


def _outcome_from_stored_result(
    turn_id: uuid.UUID, stored: Mapping[str, object]
) -> PhoneActionOutcome:
    """Reconstruct the outcome a caller would have received the first
    time, from `core.idempotency`'s own stored `result` -- never re-drives
    `CallSession`'s own state machine (the original, non-replay attempt
    already did that correctly); a lost-response retry only needs the
    answer repeated, not the turn processed twice."""
    status = stored.get("status")
    decision = cast(CallDecision, stored.get("decision", "decline"))
    if status == "success":
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision=decision,
            succeeded=True,
            replayed=True,
            result=cast("dict[str, object] | None", stored.get("output")),
        )
    if status == "pending_approval":
        output = cast("dict[str, object]", stored.get("output") or {})
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision=decision,
            succeeded=True,
            replayed=True,
            approval_id=cast("str | None", output.get("approval_id")),
        )
    return PhoneActionOutcome(
        turn_id=turn_id,
        decision=decision,
        succeeded=False,
        replayed=True,
        error_category=cast("str | None", status),
    )


async def execute_phone_action(
    session: CallSession,
    turn_id: uuid.UUID,
    *,
    tool_key: str,
    payload: Mapping[str, object],
    tenant_policy: TenantAIDataPolicy | None = None,
) -> PhoneActionOutcome:
    """Safely execute `tool_key` for the active turn `turn_id` of
    `session`, or fail closed. `tenant_id`/`actor_user_id` are always
    `session.identity`'s own fixed values -- `payload` may carry ordinary
    business input (e.g. `calendar_id`) but is never consulted for
    tenant, actor, or authorization scope. See module docstring for the
    full idempotency/decision-timing/allowlist design.

    Deliberately takes no `registry` parameter -- the tool actually
    executed always comes from this module's own `build_phone_registry()`,
    never from anything a caller (trusted or not) can supply. See module
    docstring's own "`execute_phone_action()` never accepts a
    caller-supplied `ToolRegistry`" section for why."""
    identity = session.identity
    active_registry = build_phone_registry()

    if tool_key not in PHONE_SAFE_CAPABILITIES:
        session.mark_interpreted(turn_id)
        session.mark_decided(turn_id)
        turn = session.apply_decision(
            turn_id,
            json.dumps({"decision": "decline", "decline_reason": "not available on this channel"}),
        )
        record_turn_audit(
            tenant_id=identity.tenant_id,
            actor_user_id=identity.receptionist_actor_user_id,
            call_id=identity.call_id,
            session_id=identity.session_id,
            turn=turn,
            action=_AUDIT_ACTION_DECLINED,
            outcome=AuditOutcome.DENIED,
            error_category="capability_not_allowlisted",
        )
        session.complete_turn(turn_id)
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision="decline",
            succeeded=False,
            replayed=False,
            error_category="capability_not_allowlisted",
        )

    tool = active_registry.get(tool_key)

    operation = f"telephony.phone_action.{tool_key}"
    idempotency_key = f"{identity.call_id}.{identity.session_id}.{turn_id}"
    reservation = begin_idempotent_operation(
        identity.tenant_id, operation, idempotency_key, dict(payload)
    )

    if reservation.is_replay:
        return _outcome_from_stored_result(turn_id, reservation.result or {})

    authorized = _receptionist_authorized(
        tool, actor_user_id=identity.receptionist_actor_user_id, tenant_id=identity.tenant_id
    )

    session.mark_interpreted(turn_id)
    session.mark_decided(turn_id)

    if not authorized:
        turn = session.apply_decision(
            turn_id,
            json.dumps(
                {"decision": "decline", "decline_reason": "not authorized for this request"}
            ),
        )
        session.complete_turn(turn_id)
        finalize_idempotent_operation(
            identity.tenant_id,
            reservation.record_id,
            status=IdempotencyStatus.FAILED,
            result={"status": "declined", "decision": "decline"},
        )
        record_turn_audit(
            tenant_id=identity.tenant_id,
            actor_user_id=identity.receptionist_actor_user_id,
            call_id=identity.call_id,
            session_id=identity.session_id,
            turn=turn,
            action=_AUDIT_ACTION_DENIED,
            outcome=AuditOutcome.DENIED,
            error_category="unauthorized",
        )
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision="decline",
            succeeded=False,
            replayed=False,
            error_category="unauthorized",
        )

    decision: CallDecision = "escalate" if tool.autonomy_tier >= 1 else "attempt"
    turn = session.apply_decision(turn_id, json.dumps({"decision": decision}))

    try:
        result = await invoke_product_ai_tool(
            tool_key,
            actor_user_id=identity.receptionist_actor_user_id,
            tenant_id=identity.tenant_id,
            resource_type=CALENDAR_RESOURCE,
            resource_id=None,
            payload=payload,
            tenant_policy=tenant_policy,
            registry=active_registry,
        )
    except (UnauthorizedToolInvocationError, DataAuthorizationRequiredError) as exc:
        session.complete_turn(turn_id)
        finalize_idempotent_operation(
            identity.tenant_id,
            reservation.record_id,
            status=IdempotencyStatus.FAILED,
            result={"status": "denied"},
        )
        record_turn_audit(
            tenant_id=identity.tenant_id,
            actor_user_id=identity.receptionist_actor_user_id,
            call_id=identity.call_id,
            session_id=identity.session_id,
            turn=turn,
            action=_AUDIT_ACTION_DENIED,
            outcome=AuditOutcome.DENIED,
            error_category=type(exc).__name__,
        )
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision=decision,
            succeeded=False,
            replayed=False,
            error_category=type(exc).__name__,
        )
    except ToolExecutionError:
        session.complete_turn(turn_id)
        finalize_idempotent_operation(
            identity.tenant_id,
            reservation.record_id,
            status=IdempotencyStatus.FAILED,
            result={"status": "error"},
        )
        record_turn_audit(
            tenant_id=identity.tenant_id,
            actor_user_id=identity.receptionist_actor_user_id,
            call_id=identity.call_id,
            session_id=identity.session_id,
            turn=turn,
            action=_AUDIT_ACTION_FAILED,
            outcome=AuditOutcome.FAILURE,
            error_category="tool_execution_error",
        )
        return PhoneActionOutcome(
            turn_id=turn_id,
            decision=decision,
            succeeded=False,
            replayed=False,
            error_category="tool_execution_error",
        )

    session.set_invocation_correlation(turn_id, result.correlation_id)
    session.complete_turn(turn_id)

    is_pending_approval = (
        isinstance(result.output, dict) and result.output.get("status") == "pending_approval"
    )
    stored_result: dict[str, object] = {
        "status": "pending_approval" if is_pending_approval else "success",
        "decision": decision,
        "output": result.output,
    }
    finalize_idempotent_operation(
        identity.tenant_id,
        reservation.record_id,
        status=IdempotencyStatus.SUCCEEDED,
        result=stored_result,
    )
    record_turn_audit(
        tenant_id=identity.tenant_id,
        actor_user_id=identity.receptionist_actor_user_id,
        call_id=identity.call_id,
        session_id=identity.session_id,
        turn=turn,
        action=_AUDIT_ACTION_PENDING_APPROVAL if is_pending_approval else _AUDIT_ACTION_SUCCEEDED,
        outcome=AuditOutcome.SUCCESS,
    )
    return PhoneActionOutcome(
        turn_id=turn_id,
        decision=decision,
        succeeded=True,
        replayed=False,
        result=None if is_pending_approval else result.output,
        approval_id=cast(str, result.output.get("approval_id")) if is_pending_approval else None,
    )


__all__ = [
    "APPOINTMENT_AVAILABILITY_TOOL_KEY",
    "PHONE_SAFE_CAPABILITIES",
    "PhoneActionOutcome",
    "build_phone_registry",
    "ensure_phone_safe_permissions",
    "execute_phone_action",
]
