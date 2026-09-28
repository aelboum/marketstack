"""`product/telephony/call_session.py` -- ephemeral session/turn state,
lifecycle, decision contract, ordering/idempotency (docs/ROADMAP.md Phase
27.1). No database, no network -- a plain unit test, part of the default
`pytest` run.
"""

from __future__ import annotations

import dataclasses
import json
import uuid

import pytest
from product.telephony.call_session import (
    MAX_CLARIFICATION_QUESTION_CHARS,
    MAX_DECLINE_REASON_CHARS,
    MAX_TURNS_PER_SESSION,
    TURN_STATE_ACTION_PENDING,
    TURN_STATE_CLARIFICATION_PENDING,
    TURN_STATE_COMPLETED,
    TURN_STATE_DECIDED,
    TURN_STATE_DECLINED,
    TURN_STATE_ESCALATION_PENDING,
    TURN_STATE_INTERPRETED,
    TURN_STATE_RECEIVED,
    CallSession,
    SessionIdentity,
    parse_call_decision,
)
from product.telephony.errors import CallSessionInvalidTransitionError, TelephonyValidationError


def _identity(**overrides: object) -> SessionIdentity:
    defaults: dict[str, object] = {
        "session_id": uuid.uuid4(),
        "call_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "receptionist_actor_user_id": uuid.uuid4(),
    }
    defaults.update(overrides)
    return SessionIdentity(**defaults)  # type: ignore[arg-type]


def _completion(**fields: object) -> str:
    return json.dumps(fields)


def _advance_to_decided(session: CallSession, turn_id: uuid.UUID) -> None:
    session.mark_interpreted(turn_id)
    session.mark_decided(turn_id)


# --- decision parsing --------------------------------------------------


@pytest.mark.parametrize("decision", ["attempt", "escalate"])
def test_parse_decision_without_required_metadata(decision: str) -> None:
    parsed, metadata = parse_call_decision(_completion(decision=decision))
    assert parsed == decision
    assert metadata == {}


def test_parse_clarify_requires_bounded_question() -> None:
    parsed, metadata = parse_call_decision(
        _completion(decision="clarify", clarification_question="Which day works for you?")
    )
    assert parsed == "clarify"
    assert metadata == {"clarification_question": "Which day works for you?"}


def test_parse_decline_requires_bounded_reason() -> None:
    parsed, metadata = parse_call_decision(
        _completion(decision="decline", decline_reason="Outside supported scope.")
    )
    assert parsed == "decline"
    assert metadata == {"decline_reason": "Outside supported scope."}


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        "[]",
        _completion(),  # decision missing
        _completion(decision="maybe"),
        _completion(decision=""),
        _completion(decision=None),
        _completion(decision=123),
        _completion(decision="clarify"),  # missing clarification_question
        _completion(decision="clarify", clarification_question=""),
        _completion(decision="clarify", clarification_question=123),
        _completion(
            decision="clarify",
            clarification_question="x" * (MAX_CLARIFICATION_QUESTION_CHARS + 1),
        ),
        _completion(decision="decline"),  # missing decline_reason
        _completion(decision="decline", decline_reason=""),
        _completion(decision="decline", decline_reason=[]),
        _completion(decision="decline", decline_reason="x" * (MAX_DECLINE_REASON_CHARS + 1)),
    ],
)
def test_parse_malformed_decision_rejected(raw: str) -> None:
    with pytest.raises(TelephonyValidationError):
        parse_call_decision(raw)


def test_malformed_decision_never_becomes_attempt() -> None:
    with pytest.raises(TelephonyValidationError) as excinfo:
        parse_call_decision(_completion(decision="not_a_real_decision"))
    assert "attempt" not in str(excinfo.value)


def test_decision_error_never_leaks_raw_completion_text() -> None:
    secret_marker = "TOTALLY_SECRET_RAW_TRANSCRIPT_MARKER"
    with pytest.raises(TelephonyValidationError) as excinfo:
        parse_call_decision(secret_marker)
    assert secret_marker not in str(excinfo.value)


# --- session / tenant binding -------------------------------------------


def test_session_identity_is_immutable() -> None:
    session = CallSession(_identity())
    with pytest.raises(dataclasses.FrozenInstanceError):
        session.identity.tenant_id = uuid.uuid4()  # type: ignore[misc]


def test_session_identity_attribute_cannot_be_reassigned() -> None:
    session = CallSession(_identity())
    with pytest.raises(AttributeError):
        session.identity = _identity()  # type: ignore[misc]


def test_turn_identity_is_immutable() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.identity.turn_id = uuid.uuid4()  # type: ignore[misc]


def test_model_or_caller_cannot_override_bound_tenant() -> None:
    """There is no parameter anywhere in this module's own API that
    accepts a tenant_id after session creation -- start_turn()/
    mark_interpreted()/mark_decided()/apply_decision()/complete_turn()/
    set_invocation_correlation() all take only a turn_id. This test
    documents that structural fact by exhaustively checking the session's
    own bound tenant never changes across a full turn lifecycle."""
    identity = _identity()
    session = CallSession(identity)
    turn = session.start_turn()
    _advance_to_decided(session, turn.turn_id)
    session.apply_decision(turn.turn_id, _completion(decision="attempt"))
    session.complete_turn(turn.turn_id)
    assert session.identity.tenant_id == identity.tenant_id
    assert session.identity == identity


# --- turn lifecycle -------------------------------------------------------


def test_turn_starts_in_received_state() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    assert turn.state == TURN_STATE_RECEIVED
    assert turn.sequence == 0


def test_sequence_numbers_increase_per_turn() -> None:
    session = CallSession(_identity())
    first = session.start_turn()
    _advance_to_decided(session, first.turn_id)
    session.apply_decision(first.turn_id, _completion(decision="attempt"))
    session.complete_turn(first.turn_id)

    second = session.start_turn()
    assert second.sequence == first.sequence + 1


@pytest.mark.parametrize(
    "decision,expected_state",
    [
        ("attempt", TURN_STATE_ACTION_PENDING),
        ("clarify", TURN_STATE_CLARIFICATION_PENDING),
        ("escalate", TURN_STATE_ESCALATION_PENDING),
        ("decline", TURN_STATE_DECLINED),
    ],
)
def test_each_decision_reaches_its_own_pending_state(decision: str, expected_state: str) -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    _advance_to_decided(session, turn.turn_id)
    raw = (
        _completion(decision=decision, clarification_question="Which day?")
        if decision == "clarify"
        else _completion(decision=decision, decline_reason="Not supported.")
        if decision == "decline"
        else _completion(decision=decision)
    )
    updated = session.apply_decision(turn.turn_id, raw)
    assert updated.state == expected_state
    assert updated.decision == decision

    completed = session.complete_turn(turn.turn_id)
    assert completed.state == TURN_STATE_COMPLETED
    assert session.active_turn_id is None


def test_valid_transition_sequence() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    assert session.mark_interpreted(turn.turn_id).state == TURN_STATE_INTERPRETED
    assert session.mark_decided(turn.turn_id).state == TURN_STATE_DECIDED


def test_invalid_transition_rejected() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    with pytest.raises(CallSessionInvalidTransitionError):
        session.mark_decided(turn.turn_id)  # received -> decided is not allowed


def test_duplicate_same_state_transition_is_idempotent_no_op() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    session.mark_interpreted(turn.turn_id)
    again = session.mark_interpreted(turn.turn_id)  # identical event delivered twice
    assert again.state == TURN_STATE_INTERPRETED


def test_terminal_state_cannot_be_reopened() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    _advance_to_decided(session, turn.turn_id)
    session.apply_decision(turn.turn_id, _completion(decision="attempt"))
    session.complete_turn(turn.turn_id)
    with pytest.raises(CallSessionInvalidTransitionError):
        session.mark_interpreted(turn.turn_id)


def test_apply_decision_out_of_order_rejected() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    with pytest.raises(CallSessionInvalidTransitionError):
        # never interpreted/decided yet
        session.apply_decision(turn.turn_id, _completion(decision="attempt"))


def test_malformed_decision_does_not_mutate_turn_state() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    _advance_to_decided(session, turn.turn_id)
    with pytest.raises(TelephonyValidationError):
        session.apply_decision(turn.turn_id, _completion(decision="not_real"))
    # Turn is left exactly where it was -- never silently advanced.
    assert session.get_turn(turn.turn_id).state == TURN_STATE_DECIDED
    assert session.get_turn(turn.turn_id).decision is None


# --- ordering / stale / duplicate / concurrency guarantees ----------------


def test_only_one_active_turn_per_session() -> None:
    session = CallSession(_identity())
    session.start_turn()
    with pytest.raises(TelephonyValidationError):
        session.start_turn()


def test_second_turn_can_start_after_first_completes() -> None:
    session = CallSession(_identity())
    first = session.start_turn()
    _advance_to_decided(session, first.turn_id)
    session.apply_decision(first.turn_id, _completion(decision="attempt"))
    session.complete_turn(first.turn_id)
    second = session.start_turn()
    assert second.turn_id != first.turn_id


def test_stale_turn_cannot_mutate_current_session_state() -> None:
    """An older turn (already superseded because the session moved on)
    must never be able to mutate state as if it were current."""
    session = CallSession(_identity())
    first = session.start_turn()
    _advance_to_decided(session, first.turn_id)
    session.apply_decision(first.turn_id, _completion(decision="attempt"))
    session.complete_turn(first.turn_id)

    second = session.start_turn()
    session.mark_interpreted(second.turn_id)

    # A stale attempt to advance the OLD (already-completed) turn further
    # must be rejected, never silently applied, and must not affect the
    # genuinely active second turn.
    with pytest.raises(CallSessionInvalidTransitionError):
        session.mark_interpreted(first.turn_id)
    assert session.get_turn(second.turn_id).state == TURN_STATE_INTERPRETED


def test_duplicate_turn_delivery_is_a_no_op_not_a_second_turn() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    session.mark_interpreted(turn.turn_id)
    # Re-delivering the exact same "interpreted" event twice must not
    # create a new turn or change the sequence/turn count.
    session.mark_interpreted(turn.turn_id)
    assert len(session._turns) == 1  # noqa: SLF001 -- whitebox check, test-only


def test_bounded_turn_count() -> None:
    session = CallSession(_identity())
    for _ in range(MAX_TURNS_PER_SESSION):
        turn = session.start_turn()
        _advance_to_decided(session, turn.turn_id)
        session.apply_decision(turn.turn_id, _completion(decision="attempt"))
        session.complete_turn(turn.turn_id)
    with pytest.raises(TelephonyValidationError):
        session.start_turn()


def test_invocation_correlation_recorded_on_active_turn() -> None:
    session = CallSession(_identity())
    turn = session.start_turn()
    updated = session.set_invocation_correlation(turn.turn_id, "corr-123")
    assert updated.ai_invocation_correlation_id == "corr-123"


def test_invocation_correlation_rejected_for_non_active_turn() -> None:
    session = CallSession(_identity())
    first = session.start_turn()
    _advance_to_decided(session, first.turn_id)
    session.apply_decision(first.turn_id, _completion(decision="attempt"))
    session.complete_turn(first.turn_id)
    session.start_turn()
    with pytest.raises(CallSessionInvalidTransitionError):
        session.set_invocation_correlation(first.turn_id, "stale-corr")
