"""`parse_qualify_lead_completion()` -- the pure structured-decision parser
(docs/ROADMAP.md Phase 26A, `product/ai/tools/lead_qualification.py`). No
database, no network, no provider -- a plain unit test, part of the
default `pytest` run, mirrors `tests/ai/test_receptionist_decision_unit.py`'s
own "test the pure decision function directly" convention.
"""

from __future__ import annotations

import json

import pytest
from product.ai.errors import AIProviderError
from product.ai.provider import MAX_OUTPUT_CHARS
from product.ai.tools.lead_qualification import (
    MAX_REASON_CHARS,
    parse_qualify_lead_completion,
)


def _completion(**fields: object) -> str:
    return json.dumps(fields)


@pytest.mark.parametrize("decision", ["qualified", "not_qualified", "needs_more_info"])
def test_valid_decision_parses(decision: str) -> None:
    raw = _completion(decision=decision, reason="Short reason.", qualification="A note.")
    parsed_decision, reason, qualification = parse_qualify_lead_completion(raw)
    assert parsed_decision == decision
    assert reason == "Short reason."
    assert qualification == "A note."


@pytest.mark.parametrize("decision", ["maybe", "high", "", None, 123])
def test_invalid_decision_rejected(decision: object) -> None:
    raw = _completion(decision=decision, reason="x", qualification="y")
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion(raw)


@pytest.mark.parametrize(
    "raw",
    [
        _completion(reason="x", qualification="y"),  # decision missing
        _completion(decision="qualified", qualification="y"),  # reason missing
        _completion(decision="qualified", reason="x"),  # qualification missing
    ],
)
def test_missing_required_field_rejected(raw: str) -> None:
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion(raw)


@pytest.mark.parametrize(
    "raw",
    [
        _completion(decision="qualified", reason=[], qualification="y"),
        _completion(decision="qualified", reason="x", qualification={}),
        _completion(decision="qualified", reason=123, qualification="y"),
        _completion(decision="qualified", reason="x", qualification=456),
    ],
)
def test_wrong_typed_field_rejected(raw: str) -> None:
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion(raw)


def test_oversized_reason_rejected_not_truncated() -> None:
    raw = _completion(
        decision="qualified", reason="x" * (MAX_REASON_CHARS + 1), qualification="y"
    )
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion(raw)


def test_oversized_qualification_rejected_not_truncated() -> None:
    raw = _completion(
        decision="qualified", reason="x", qualification="y" * (MAX_OUTPUT_CHARS + 1)
    )
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion(raw)


def test_reason_and_qualification_at_exact_bound_are_accepted() -> None:
    raw = _completion(
        decision="qualified",
        reason="x" * MAX_REASON_CHARS,
        qualification="y" * MAX_OUTPUT_CHARS,
    )
    decision, reason, qualification = parse_qualify_lead_completion(raw)
    assert decision == "qualified"
    assert len(reason) == MAX_REASON_CHARS
    assert len(qualification) == MAX_OUTPUT_CHARS


def test_non_json_completion_rejected() -> None:
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion("not json at all")


def test_json_array_completion_rejected() -> None:
    with pytest.raises(AIProviderError):
        parse_qualify_lead_completion("[]")


def test_error_never_leaks_raw_completion_text() -> None:
    """The failure must not carry the raw model response verbatim (this
    phase's own "never expose the complete raw model response" and
    `product/ai/openai_provider.py`'s own "type name and a short reason
    only" precedent)."""
    secret_marker = "TOTALLY_SECRET_RAW_MODEL_TEXT_MARKER"
    with pytest.raises(AIProviderError) as excinfo:
        parse_qualify_lead_completion(secret_marker)
    assert secret_marker not in str(excinfo.value)
