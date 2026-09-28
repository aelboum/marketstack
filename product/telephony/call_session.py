"""Ephemeral call-session and turn state (docs/ROADMAP.md Phase 27.1 --
"Call Session & Actor Foundation").

**In-process, ephemeral, never persisted.** `CallSession`/`Turn` below
hold exactly the state needed to coordinate one active conversational
call, and nothing else -- no new database table, no migration. A live
call is a real-time, single-session process, not a resumable durable
workflow: if a process holding a `CallSession` crashes mid-turn, the
correct behavior (per the Phase 27 readiness audit) is to fail toward
ordinary human routing, never to resume from a persisted checkpoint.
Mirrors Phase 26C's own "no general-purpose data-flow language, no second
workflow engine" precedent applied here by direct analogy: this module is
a small, closed, in-memory state machine, never a database-backed
conversation-history store.

**What IS durable, unchanged, and untouched by this module**:
`product/telephony/models.py::Call`/`CallEvent` (the call's own summary
row and event ledger), `core.audit_log` entries this module writes via
`record_turn_audit()` below, and whatever real business-action side
effect (a CRM mutation, an `ApprovalRequest`) a later phase's own
invocation of Phase 26 actually produces. This module never calls
`product/ai/invocation.py::invoke_product_ai_tool()`/
`execute_approved_ai_tool()` itself -- it has no import on `product.ai`
or `control_plane` at all (`product.telephony` is not permitted to depend
on `product.ai`; the reverse edge is the one this repository's own
import-linter contract allows) -- it only holds the `tenant_id`/
`receptionist_actor_user_id` a later phase (27.2) will pass to those
functions unchanged, and a place (`ai_invocation_correlation_id`) to
record the `ToolInvocationResult.correlation_id` that call returns.

**Bounded, never a transcript store.** `MAX_TURNS_PER_SESSION` caps how
many turns one session may ever hold; `MAX_CLARIFICATION_QUESTION_CHARS`/
`MAX_DECLINE_REASON_CHARS` bound the only two free-text fields this
module's own closed decision vocabulary carries. No raw transcript, no
raw model output, and no audio are ever accepted as a field here -- there
is no parameter anywhere in this module that could hold one.

**Single-process scope, disclosed.** The `_active_turn_id`/ordering
guarantees below are enforced entirely in this process's own memory --
correct for one call handled start-to-finish by one process, which is
sufficient for everything Phase 27.1 itself needs to prove. If Phase
27.0's eventual transport/media architecture turns out to require a call
be coordinated across multiple worker processes, that is a 27.0
architectural decision this module cannot anticipate and does not
attempt to -- no distributed lock or shared cache is introduced here
speculatively."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Literal, cast

from core.audit_log import ActorType, AuditOutcome
from core.audit_log import record as record_audit_event

from product.telephony.errors import CallSessionInvalidTransitionError, TelephonyValidationError

_AUDIT_RESOURCE_TYPE = "telephony.call_session"

# --- bounds -----------------------------------------------------------------

#: A safety cap on how long one session's own turn history may grow --
#: never a target, never a real expected call length. Reaching it signals
#: something has gone wrong (a stuck loop, a runaway conversation), not a
#: legitimate very-long call.
MAX_TURNS_PER_SESSION = 50

#: `reason`/`clarification_question` are short, single-sentence fields --
#: deliberately bounded well under `product/ai/tools/lead_qualification.py
#: ::MAX_REASON_CHARS` (240)'s own sibling bound, mirrored here at the
#: identical value for the identical reason (a short field has no
#: legitimate need for more, and a smaller bound catches a
#: runaway/malformed completion sooner). Not imported from `product.ai` --
#: this module has no dependency on it at all (module docstring).
MAX_CLARIFICATION_QUESTION_CHARS = 240
MAX_DECLINE_REASON_CHARS = 240


# --- turn lifecycle -----------------------------------------------------

TURN_STATE_RECEIVED = "received"
TURN_STATE_INTERPRETED = "interpreted"
TURN_STATE_DECIDED = "decided"
TURN_STATE_ACTION_PENDING = "action_pending"
TURN_STATE_CLARIFICATION_PENDING = "clarification_pending"
TURN_STATE_ESCALATION_PENDING = "escalation_pending"
TURN_STATE_DECLINED = "declined"
TURN_STATE_COMPLETED = "completed"

#: The complete, closed transition table -- mirrors
#: `product/telephony/calls.py::_ALLOWED_TRANSITIONS`'s exact shape and
#: exact "duplicate same-state delivery is an idempotent no-op; anything
#: else not listed here is rejected loudly" discipline. Strictly forward,
#: never cyclic: a "clarify" decision means the *session* starts a new
#: turn afterward (a fresh `start_turn()` call) -- this table never loops
#: a single turn back to an earlier state.
_ALLOWED_TURN_TRANSITIONS: dict[str, frozenset[str]] = {
    TURN_STATE_RECEIVED: frozenset({TURN_STATE_INTERPRETED}),
    TURN_STATE_INTERPRETED: frozenset({TURN_STATE_DECIDED}),
    TURN_STATE_DECIDED: frozenset(
        {
            TURN_STATE_ACTION_PENDING,
            TURN_STATE_CLARIFICATION_PENDING,
            TURN_STATE_ESCALATION_PENDING,
            TURN_STATE_DECLINED,
        }
    ),
    TURN_STATE_ACTION_PENDING: frozenset({TURN_STATE_COMPLETED}),
    TURN_STATE_CLARIFICATION_PENDING: frozenset({TURN_STATE_COMPLETED}),
    TURN_STATE_ESCALATION_PENDING: frozenset({TURN_STATE_COMPLETED}),
    TURN_STATE_DECLINED: frozenset({TURN_STATE_COMPLETED}),
    TURN_STATE_COMPLETED: frozenset(),
}

_TERMINAL_TURN_STATES = frozenset({TURN_STATE_COMPLETED})

_DECISION_TO_PENDING_STATE: dict[str, str] = {
    "attempt": TURN_STATE_ACTION_PENDING,
    "clarify": TURN_STATE_CLARIFICATION_PENDING,
    "escalate": TURN_STATE_ESCALATION_PENDING,
    "decline": TURN_STATE_DECLINED,
}


# --- closed decision contract --------------------------------------------

#: The exact, closed conversational-control vocabulary (docs/ROADMAP.md
#: Phase 27.1). Mirrors `product/ai/tools/lead_qualification.py
#: ::QualifyLeadDecision`'s own tool-local `Literal` convention, applied
#: here at the call-session domain boundary instead -- never inside
#: `LLMProvider`/`SpeechProvider`/`product/ai/invocation.py`.
CallDecision = Literal["attempt", "clarify", "escalate", "decline"]

_VALID_DECISIONS: frozenset[str] = frozenset({"attempt", "clarify", "escalate", "decline"})


def parse_call_decision(raw_text: str) -> tuple[CallDecision, dict[str, str]]:
    """Deterministically parse+validate a structured JSON completion into
    `(decision, bounded_metadata)`. Mirrors `product/ai/tools
    /lead_qualification.py::parse_qualify_lead_completion()`'s own
    discipline exactly (not imported -- this module has no dependency on
    `product.ai`, module docstring): a completion that is not valid JSON,
    is missing a required field, has a wrong-typed or out-of-vocabulary
    `decision`, or exceeds the bounds above is rejected with
    `TelephonyValidationError` -- this module's own existing "caller/
    model-output shape error" convention -- never silently coerced,
    never truncated, and never defaulted to `"attempt"`.

    `clarify` requires a non-empty, bounded `clarification_question`;
    `decline` requires a non-empty, bounded `decline_reason`; `attempt`/
    `escalate` require no accompanying field (none is genuinely needed by
    this phase's own scope -- module docstring's own "only add fields
    that are genuinely required" discipline)."""
    try:
        parsed = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise TelephonyValidationError(
            "model returned a completion that was not valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise TelephonyValidationError("model returned a JSON completion that was not an object.")

    decision = parsed.get("decision")
    if decision not in _VALID_DECISIONS:
        raise TelephonyValidationError(
            "model returned a completion with a missing or invalid 'decision'."
        )

    metadata: dict[str, str] = {}
    if decision == "clarify":
        question = parsed.get("clarification_question")
        if not isinstance(question, str) or not question:
            raise TelephonyValidationError(
                "'clarify' requires a non-empty 'clarification_question'."
            )
        if len(question) > MAX_CLARIFICATION_QUESTION_CHARS:
            raise TelephonyValidationError(
                f"'clarification_question' exceeds {MAX_CLARIFICATION_QUESTION_CHARS} characters."
            )
        metadata["clarification_question"] = question
    elif decision == "decline":
        reason = parsed.get("decline_reason")
        if not isinstance(reason, str) or not reason:
            raise TelephonyValidationError("'decline' requires a non-empty 'decline_reason'.")
        if len(reason) > MAX_DECLINE_REASON_CHARS:
            raise TelephonyValidationError(
                f"'decline_reason' exceeds {MAX_DECLINE_REASON_CHARS} characters."
            )
        metadata["decline_reason"] = reason

    return cast(CallDecision, decision), metadata


# --- session / turn identity and state -----------------------------------


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    """The four values that must never change for the life of a session --
    frozen so an attempted reassignment raises `dataclasses.
    FrozenInstanceError` structurally, not merely by convention."""

    session_id: uuid.UUID
    call_id: uuid.UUID
    tenant_id: uuid.UUID
    receptionist_actor_user_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class TurnIdentity:
    """A turn's own immutable identity -- assigned exactly once by
    `CallSession.start_turn()`, never reassignable afterward."""

    turn_id: uuid.UUID
    session_id: uuid.UUID
    sequence: int


@dataclass(slots=True)
class Turn:
    """One conversational turn. `identity` is immutable (a frozen
    sub-object); `state`/`decision`/`decision_metadata`/
    `ai_invocation_correlation_id` evolve over the turn's own life, but
    only ever through `CallSession`'s own methods below -- never assigned
    directly by external code."""

    identity: TurnIdentity
    state: str = TURN_STATE_RECEIVED
    decision: CallDecision | None = None
    decision_metadata: dict[str, str] = field(default_factory=dict)
    #: Populated later, by a future phase (27.2), with the
    #: `ToolInvocationResult.correlation_id` its own
    #: `invoke_product_ai_tool()`/`execute_approved_ai_tool()` call
    #: returned -- this module never calls either function itself (module
    #: docstring) and never invents this value.
    ai_invocation_correlation_id: str | None = None

    @property
    def turn_id(self) -> uuid.UUID:
        return self.identity.turn_id

    @property
    def sequence(self) -> int:
        return self.identity.sequence


class CallSession:
    """One active call's own bounded, ephemeral coordination state.
    `identity` is exposed read-only (a property with no setter) so
    `session.identity = other_identity` fails with `AttributeError`,
    layered on top of `SessionIdentity` itself being frozen -- two
    independent enforcement mechanisms for the same "tenant/call binding
    is immutable for the life of the session" invariant, not merely a
    naming convention."""

    __slots__ = ("_identity", "_turns", "_active_turn_id", "_next_sequence")

    def __init__(self, identity: SessionIdentity) -> None:
        self._identity = identity
        self._turns: dict[uuid.UUID, Turn] = {}
        self._active_turn_id: uuid.UUID | None = None
        self._next_sequence = 0

    @property
    def identity(self) -> SessionIdentity:
        return self._identity

    @property
    def active_turn_id(self) -> uuid.UUID | None:
        return self._active_turn_id

    def get_turn(self, turn_id: uuid.UUID) -> Turn:
        turn = self._turns.get(turn_id)
        if turn is None:
            raise TelephonyValidationError(
                f"no turn {turn_id} in session {self._identity.session_id}."
            )
        return turn

    def start_turn(self) -> Turn:
        """Begin a new turn. Rejects starting a second turn while one is
        already active (docs/ROADMAP.md Phase 27.1's own "one active turn
        per session" requirement) -- audio-level concurrency/barge-in
        remain entirely a 27.0 transport concern; this is strictly the
        state-level guarantee that no second turn can become active while
        one already is."""
        if self._active_turn_id is not None:
            raise TelephonyValidationError(
                f"session {self._identity.session_id} already has an active turn "
                f"({self._active_turn_id}); complete it before starting another."
            )
        if len(self._turns) >= MAX_TURNS_PER_SESSION:
            raise TelephonyValidationError(
                f"session {self._identity.session_id} has reached the bound of "
                f"{MAX_TURNS_PER_SESSION} turns."
            )
        turn = Turn(
            identity=TurnIdentity(
                turn_id=uuid.uuid4(),
                session_id=self._identity.session_id,
                sequence=self._next_sequence,
            )
        )
        self._next_sequence += 1
        self._turns[turn.turn_id] = turn
        self._active_turn_id = turn.turn_id
        return turn

    def _transition(self, turn_id: uuid.UUID, target_state: str) -> Turn:
        """The one place every state change in this module goes through --
        mirrors `product/telephony/calls.py::_apply_transition()`'s own
        "idempotent no-op on same-state re-delivery; loud rejection of
        anything else not in the table" discipline exactly, extended with
        the stale-turn case that module does not need (a call has only
        one row; a session may have many turns, only one of them current).
        """
        turn = self.get_turn(turn_id)

        if turn_id != self._active_turn_id:
            # Not the session's own current turn -- either a duplicate
            # delivery for a turn that already reached this exact state
            # (harmless, idempotent no-op), or a genuinely stale/
            # out-of-order attempt to mutate superseded state (rejected,
            # never silently applied).
            if turn.state == target_state:
                return turn
            raise CallSessionInvalidTransitionError(
                turn_id, current_state=turn.state, requested_state=target_state
            )

        if turn.state == target_state:
            return turn  # idempotent no-op -- identical event delivered twice
        allowed = _ALLOWED_TURN_TRANSITIONS.get(turn.state, frozenset())
        if target_state not in allowed:
            raise CallSessionInvalidTransitionError(
                turn_id, current_state=turn.state, requested_state=target_state
            )
        turn.state = target_state
        if target_state in _TERMINAL_TURN_STATES:
            self._active_turn_id = None
        return turn

    def mark_interpreted(self, turn_id: uuid.UUID) -> Turn:
        return self._transition(turn_id, TURN_STATE_INTERPRETED)

    def mark_decided(self, turn_id: uuid.UUID) -> Turn:
        return self._transition(turn_id, TURN_STATE_DECIDED)

    def apply_decision(self, turn_id: uuid.UUID, raw_completion_text: str) -> Turn:
        """Parse `raw_completion_text` (`parse_call_decision()` above) and
        transition the turn from `decided` to the matching pending state.
        A malformed completion fails closed via `TelephonyValidationError`
        *before* any state mutation is attempted -- the turn is left
        exactly where it was, never advanced on invalid input and never
        defaulted to `"attempt"`."""
        decision, metadata = parse_call_decision(raw_completion_text)
        turn = self._transition(turn_id, _DECISION_TO_PENDING_STATE[decision])
        turn.decision = decision
        turn.decision_metadata = metadata
        return turn

    def complete_turn(self, turn_id: uuid.UUID) -> Turn:
        return self._transition(turn_id, TURN_STATE_COMPLETED)

    def set_invocation_correlation(self, turn_id: uuid.UUID, correlation_id: str) -> Turn:
        """Record the `ToolInvocationResult.correlation_id` a later
        phase's own `invoke_product_ai_tool()`/`execute_approved_ai_tool()`
        call returned. Metadata, not a lifecycle transition -- but guarded
        by the identical "must be the session's own current turn"
        invariant every state transition already enforces, so a stale
        turn can never attach a correlation id after the fact."""
        turn = self.get_turn(turn_id)
        if turn_id != self._active_turn_id:
            raise CallSessionInvalidTransitionError(
                turn_id, current_state=turn.state, requested_state=turn.state
            )
        turn.ai_invocation_correlation_id = correlation_id
        return turn


# --- audit correlation ----------------------------------------------------


def record_turn_audit(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    call_id: uuid.UUID,
    session_id: uuid.UUID,
    turn: Turn,
    action: str,
    outcome: AuditOutcome,
    error_category: str | None = None,
) -> None:
    """Reuses `core.audit_log.record()` unchanged -- no new audit
    infrastructure. Carries exactly the correlation metadata Phase 27.1
    needs to reconstruct `call -> session -> turn -> (Phase 26 invocation)`
    from the audit trail alone: `call_id`/`session_id`/`turn_id`, the
    receptionist actor, the turn's own decision (once known), and its
    `ai_invocation_correlation_id` (once a later phase has set one) --
    never the raw transcript or raw model output, which have no field to
    even be placed in here (module docstring)."""
    metadata: dict[str, object] = {
        "call_id": str(call_id),
        "session_id": str(session_id),
        "turn_id": str(turn.turn_id),
        "sequence": turn.sequence,
        "turn_state": turn.state,
    }
    if turn.decision is not None:
        metadata["decision"] = turn.decision
    if turn.ai_invocation_correlation_id is not None:
        metadata["ai_invocation_correlation_id"] = turn.ai_invocation_correlation_id
    if error_category is not None:
        metadata["error_category"] = error_category

    record_audit_event(
        tenant_id=tenant_id,
        actor_type=ActorType.USER,
        actor_user_id=actor_user_id,
        action=action,
        resource_type=_AUDIT_RESOURCE_TYPE,
        resource_id=str(session_id),
        outcome=outcome,
        metadata=metadata,
    )


__all__ = [
    "MAX_CLARIFICATION_QUESTION_CHARS",
    "MAX_DECLINE_REASON_CHARS",
    "MAX_TURNS_PER_SESSION",
    "TURN_STATE_ACTION_PENDING",
    "TURN_STATE_CLARIFICATION_PENDING",
    "TURN_STATE_COMPLETED",
    "TURN_STATE_DECIDED",
    "TURN_STATE_DECLINED",
    "TURN_STATE_ESCALATION_PENDING",
    "TURN_STATE_INTERPRETED",
    "TURN_STATE_RECEIVED",
    "CallDecision",
    "CallSession",
    "SessionIdentity",
    "Turn",
    "TurnIdentity",
    "parse_call_decision",
    "record_turn_audit",
]
