"""`send_webhook`'s SSRF-hardening + action_config validation (docs/ROADMAP.md
Phase 10.2). No database, no real network call -- a plain unit test, part
of the default `pytest` run.
"""

from __future__ import annotations

import pytest
from product.automation.actions import (
    ACTION_CREATE_TASK,
    ACTION_MOVE_OPPORTUNITY,
    ACTION_SEND_EMAIL,
    ACTION_SEND_WEBHOOK,
    ACTION_UPDATE_CONTACT,
    ACTIONS,
    validate_action_config,
    validate_action_type,
)
from product.automation.errors import AutomationActionError, AutomationValidationError


def test_validate_action_type_accepts_known_types() -> None:
    for action_type in ACTIONS:
        validate_action_type(action_type)  # must not raise


def test_validate_action_type_rejects_unknown() -> None:
    with pytest.raises(AutomationValidationError):
        validate_action_type("delete_everything")


def test_create_task_requires_title() -> None:
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_CREATE_TASK, {})
    validate_action_config(ACTION_CREATE_TASK, {"title": "Follow up"})


def test_update_contact_config_is_fully_optional() -> None:
    validate_action_config(ACTION_UPDATE_CONTACT, {})  # must not raise


def test_move_opportunity_requires_valid_stage_uuid() -> None:
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_MOVE_OPPORTUNITY, {})
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_MOVE_OPPORTUNITY, {"to_stage_id": "not-a-uuid"})
    validate_action_config(
        ACTION_MOVE_OPPORTUNITY, {"to_stage_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}
    )


def test_send_email_requires_to_subject_body() -> None:
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_SEND_EMAIL, {"to": "a@example.com"})
    validate_action_config(
        ACTION_SEND_EMAIL, {"to": "a@example.com", "subject": "Hi", "body": "Hello"}
    )


def test_send_webhook_requires_https_url() -> None:
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "http://example.com/hook"})
    with pytest.raises(AutomationValidationError):
        validate_action_config(ACTION_SEND_WEBHOOK, {})


def test_send_webhook_rejects_loopback_address() -> None:
    with pytest.raises(AutomationActionError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "https://127.0.0.1/hook"})


def test_send_webhook_rejects_private_address() -> None:
    with pytest.raises(AutomationActionError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "https://10.0.0.5/hook"})
    with pytest.raises(AutomationActionError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "https://192.168.1.1/hook"})


def test_send_webhook_rejects_link_local_address() -> None:
    with pytest.raises(AutomationActionError):
        validate_action_config(ACTION_SEND_WEBHOOK, {"url": "https://169.254.169.254/hook"})
