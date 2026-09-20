"""`decide_receptionist_action()` -- the pure confidence-boundary decision
(docs/ROADMAP.md Phase 9.2). No database, no network, no provider -- a
plain unit test, part of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.ai.errors import AIValidationError
from product.ai.receptionist import ESCALATION_CONFIDENCE_THRESHOLD, decide_receptionist_action


def test_confidence_at_or_above_threshold_handles() -> None:
    assert decide_receptionist_action(ESCALATION_CONFIDENCE_THRESHOLD) == "handle"
    assert decide_receptionist_action(1.0) == "handle"


def test_confidence_below_threshold_escalates() -> None:
    assert decide_receptionist_action(ESCALATION_CONFIDENCE_THRESHOLD - 0.01) == "escalate"
    assert decide_receptionist_action(0.0) == "escalate"


def test_confidence_above_one_rejected() -> None:
    with pytest.raises(AIValidationError):
        decide_receptionist_action(1.01)


def test_confidence_below_zero_rejected() -> None:
    with pytest.raises(AIValidationError):
        decide_receptionist_action(-0.01)
