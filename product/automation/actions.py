"""The single-step action library (docs/ROADMAP.md Phase 10.2's own
action list). A closed, enum-like `action_type` vocabulary -- `ACTIONS`
below is the *only* set of things a workflow can ever do; there is no
path from a workflow definition to arbitrary code, an arbitrary function,
or an arbitrary shell command (this phase's own explicit prohibition).

**Registering an action from another product domain (Phase 10.3A).**
Since 10.3A each action is one `product.foundation.workflow_actions
.WorkflowActionSpec` in a `WorkflowActionRegistry`, rather than an entry
in three parallel structures (`ACTIONS`, an if/elif validation chain, and
an `_EXECUTORS` dict) that could drift apart. The registry is what makes
Phase 10.4A's AI action reachable *without* `product.automation`
importing `product.ai` -- an import the import-linter contracts forbid in
both directions (see `product/foundation/workflow_actions.py`'s own
module docstring for the full reasoning and the inverted dependency
diagram). A foreign domain's adapter is registered by a composition root
through `get_action_registry()`, never by an import side effect of the
domain package.

The closed vocabulary itself is unaffected by any of that: `ACTIONS`
below is a static constant, and `validate_action_type()` consults it
directly, so which workflow definitions are publishable can never vary
with import order or with what a given process has wired up. Today
`ACTIONS` still names exactly Phase 10.2's own five actions -- 10.3A adds
the mechanism, not a sixth action.

**Every action re-authorizes as the workflow's own `created_by_user_id`,
never as a synthetic "automation" identity** -- `create_task`/
`update_contact`/`move_opportunity` each call straight into
`product.crm`'s own published functions (`docs/ADR/0008-automation-depends-on-crm.md`),
whose own `require()` call is the real, live authorization boundary. An
automation is never a privilege-escalation path: if the creator's access
is later revoked, the next execution fails at that same `require()` call,
exactly as if the creator had tried the action directly.

**`send_email`/`send_webhook` need no product-module dependency**:
`send_email` reuses `core.email.send_email()` directly (Category A, a
real default SMTP provider already exists -- unlike `product.telephony
`/`product.conversations.sms`'s own "no vendor" situation, email sending
is genuinely production-real today). `send_webhook` is a new,
Product-owned, SSRF-hardened HTTP client -- `core.webhooks`' own
equivalent hardening (`_validate_destination`/`_pin_url_to_validated_address`
in the installed `saas-os` package) is private to that module's own
subscription-delivery flow, not exported, and answers a different
question besides (deliver to one of a tenant's *registered*
subscriptions, never an arbitrary per-workflow target URL configured as
part of *this* action). This module's own `_validate_webhook_url()` is a
narrow, from-scratch equivalent for that different, real need -- see its
own docstring for the exact checks.

**No templating language** -- `action_config` values are static, literal
strings the tenant configured; the only *dynamic* data an action ever
sees is a small, fixed set of well-known ids
(`contact_id`/`opportunity_id`) automatically extracted from the
triggering event's own payload when present (`_extract_trigger_ids()`),
never a caller-suppliable template/expression evaluated against
arbitrary payload content. This is a deliberate scope cut, not an
oversight -- a template language is its own injection-adjacent surface,
and the roadmap's own 10.2 scope names "single-step actions," not a
templating engine.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import uuid
from collections.abc import Mapping
from urllib.parse import urlparse

import httpx
from core.email import EmailMessage, get_email_config
from core.email import send_email as _send_email
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError

from product.automation.errors import AutomationActionError, AutomationValidationError
from product.crm.activities import create_task
from product.crm.contacts import update_contact
from product.crm.opportunities import change_stage
from product.foundation.workflow_actions import (
    UnknownWorkflowActionError,
    WorkflowActionRegistry,
    WorkflowActionSpec,
)

MAX_ACTION_CONFIG_STRING_CHARS = 4_000
MAX_WEBHOOK_BODY_BYTES = 16_384
MAX_WEBHOOK_RESPONSE_BYTES = 4_096
WEBHOOK_TIMEOUT_SECONDS = 5.0

ACTION_CREATE_TASK = "create_task"
ACTION_UPDATE_CONTACT = "update_contact"
ACTION_MOVE_OPPORTUNITY = "move_opportunity"
ACTION_SEND_EMAIL = "send_email"
ACTION_SEND_WEBHOOK = "send_webhook"

ACTIONS = frozenset(
    {
        ACTION_CREATE_TASK,
        ACTION_UPDATE_CONTACT,
        ACTION_MOVE_OPPORTUNITY,
        ACTION_SEND_EMAIL,
        ACTION_SEND_WEBHOOK,
    }
)


def validate_action_type(action_type: str) -> None:
    if action_type not in ACTIONS:
        raise AutomationValidationError(
            f"action_type must be one of {sorted(ACTIONS)}, got {action_type!r}."
        )


def _extract_trigger_ids(payload: Mapping[str, object]) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for key in ("contact_id", "opportunity_id"):
        raw = payload.get(key)
        if isinstance(raw, str):
            try:
                ids[key] = uuid.UUID(raw)
            except ValueError:
                continue
    return ids


def _config_string(config: Mapping[str, object], key: str, *, required: bool) -> str | None:
    raw = config.get(key)
    if raw is None:
        if required:
            raise AutomationValidationError(f"action_config.{key} is required.")
        return None
    if not isinstance(raw, str):
        raise AutomationValidationError(f"action_config.{key} must be a string.")
    if len(raw) > MAX_ACTION_CONFIG_STRING_CHARS:
        raise AutomationValidationError(
            f"action_config.{key} exceeds {MAX_ACTION_CONFIG_STRING_CHARS} characters."
        )
    return raw


# --- create_task --------------------------------------------------------


def _execute_create_task(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    title = _config_string(action_config, "title", required=True)
    description = _config_string(action_config, "description", required=False)
    trigger_ids = _extract_trigger_ids(payload)
    view = create_task(
        actor_user_id,
        tenant_id,
        title=title,  # type: ignore[arg-type] -- required=True guarantees non-None
        description=description,
        contact_id=trigger_ids.get("contact_id"),
        opportunity_id=trigger_ids.get("opportunity_id"),
    )
    return {"task_id": str(view.id)}


# --- update_contact -------------------------------------------------------


def _execute_update_contact(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    trigger_ids = _extract_trigger_ids(payload)
    contact_id = trigger_ids.get("contact_id")
    if contact_id is None:
        raise AutomationActionError(
            "update_contact requires a contact_id in the triggering event's own payload."
        )
    first_name = _config_string(action_config, "first_name", required=False)
    last_name = _config_string(action_config, "last_name", required=False)
    email = _config_string(action_config, "email", required=False)
    phone = _config_string(action_config, "phone", required=False)
    view = update_contact(
        actor_user_id,
        tenant_id,
        contact_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
    )
    return {"contact_id": str(view.id)}


# --- move_opportunity -----------------------------------------------------


def _execute_move_opportunity(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    trigger_ids = _extract_trigger_ids(payload)
    opportunity_id = trigger_ids.get("opportunity_id")
    if opportunity_id is None:
        raise AutomationActionError(
            "move_opportunity requires an opportunity_id in the triggering event's own payload."
        )
    to_stage_id_raw = _config_string(action_config, "to_stage_id", required=True)
    try:
        to_stage_id = uuid.UUID(to_stage_id_raw)  # type: ignore[arg-type]
    except ValueError as exc:
        raise AutomationValidationError("action_config.to_stage_id must be a valid UUID.") from exc
    view = change_stage(actor_user_id, tenant_id, opportunity_id, to_stage_id)
    return {"opportunity_id": str(view.id), "stage_id": str(view.stage_id)}


# --- send_email -------------------------------------------------------------


def _execute_send_email(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    to = _config_string(action_config, "to", required=True)
    subject = _config_string(action_config, "subject", required=True)
    body = _config_string(action_config, "body", required=True)
    config = get_email_config()
    if not config.default_sender:
        raise AutomationActionError("EMAIL_DEFAULT_SENDER is not set.")
    message = EmailMessage(sender=config.default_sender, to=(to,), subject=subject, text_body=body)  # type: ignore[arg-type]
    try:
        result = _send_email(message)
    except (EmailConfigurationError, EmailProviderError, InvalidEmailAddressError) as exc:
        raise AutomationActionError(f"send_email failed: {type(exc).__name__}") from exc
    return {"accepted": result.accepted}


# --- send_webhook (SSRF-hardened) -----------------------------------------


def _reject_non_public_address(hostname: str) -> None:
    """Resolves `hostname` and rejects the whole call if *any* resolved
    address is not a genuine public unicast address -- private, loopback,
    link-local, multicast, reserved, or unspecified. A hostname resolving
    to *multiple* addresses (DNS load balancing, or an attacker-controlled
    record deliberately mixing a public and a private answer) is rejected
    entirely, not partially -- the connection is never pinned to
    "whichever address happened to pass," see module docstring for why
    this is a from-scratch equivalent of `core.webhooks`'s own private
    logic, not a reuse of it."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise AutomationActionError(f"send_webhook: could not resolve host {hostname!r}.") from exc
    if not infos:
        raise AutomationActionError(f"send_webhook: could not resolve host {hostname!r}.")
    for _family, _type, _proto, _canonname, sockaddr in infos:
        raw_address = sockaddr[0]
        address = ipaddress.ip_address(raw_address)
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise AutomationActionError(
                f"send_webhook: {hostname!r} resolves to a non-public address; refused."
            )


def _validate_webhook_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise AutomationValidationError("action_config.url must use https.")
    if not parsed.hostname:
        raise AutomationValidationError("action_config.url must include a hostname.")
    _reject_non_public_address(parsed.hostname)


def _execute_send_webhook(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    url = _config_string(action_config, "url", required=True)
    assert url is not None  # required=True guarantees non-None
    _validate_webhook_url(url)

    body_bytes = json.dumps({"event": dict(payload)}, default=str).encode("utf-8")
    if len(body_bytes) > MAX_WEBHOOK_BODY_BYTES:
        raise AutomationValidationError(
            f"send_webhook payload exceeds {MAX_WEBHOOK_BODY_BYTES} bytes."
        )

    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(
                url, content=body_bytes, headers={"Content-Type": "application/json"}
            )
    except httpx.HTTPError as exc:
        raise AutomationActionError(f"send_webhook failed: {type(exc).__name__}") from exc

    return {
        "status_code": response.status_code,
        "response_excerpt": response.text[:MAX_WEBHOOK_RESPONSE_BYTES],
    }


# --- per-action config validation ------------------------------------------
# One function per action, replacing the single if/elif chain this module
# carried before Phase 10.3A. Behaviour is unchanged, branch for branch --
# splitting them is what lets each action be expressed as one
# `WorkflowActionSpec` (name + validate + execute) instead of being spread
# across three parallel structures (`ACTIONS`, the chain, `_EXECUTORS`)
# that could silently disagree with one another.


def _validate_create_task_config(action_config: Mapping[str, object]) -> None:
    _config_string(action_config, "title", required=True)


def _validate_update_contact_config(action_config: Mapping[str, object]) -> None:
    # every field is optional; a no-op update is a caller choice, not invalid
    return None


def _validate_move_opportunity_config(action_config: Mapping[str, object]) -> None:
    raw = _config_string(action_config, "to_stage_id", required=True)
    try:
        uuid.UUID(raw)  # type: ignore[arg-type]
    except ValueError as exc:
        raise AutomationValidationError("action_config.to_stage_id must be a valid UUID.") from exc


def _validate_send_email_config(action_config: Mapping[str, object]) -> None:
    _config_string(action_config, "to", required=True)
    _config_string(action_config, "subject", required=True)
    _config_string(action_config, "body", required=True)


def _validate_send_webhook_config(action_config: Mapping[str, object]) -> None:
    url = _config_string(action_config, "url", required=True)
    _validate_webhook_url(url)  # type: ignore[arg-type]


# --- registry ---------------------------------------------------------------


def _build_registry() -> WorkflowActionRegistry:
    """Construct this module's registry and register the five actions
    Automation itself owns. Called exactly once, unconditionally, at this
    module's own import -- which is *not* the import-order-dependent
    registration this phase exists to avoid: these five actions live in
    this very module, so importing `product.automation.actions` always
    produces the identical, complete registry, with no dependence on what
    else the interpreter has loaded. `require_complete()` proves it before
    the module finishes importing.

    A *foreign* domain's action (Phase 10.4A's AI action being the first)
    is registered differently and deliberately so -- see this module's own
    "Registering an action from another product domain" note below."""
    registry = WorkflowActionRegistry(allowed_names=ACTIONS)
    for spec in (
        WorkflowActionSpec(
            name=ACTION_CREATE_TASK,
            validate_config=_validate_create_task_config,
            execute=_execute_create_task,
        ),
        WorkflowActionSpec(
            name=ACTION_UPDATE_CONTACT,
            validate_config=_validate_update_contact_config,
            execute=_execute_update_contact,
        ),
        WorkflowActionSpec(
            name=ACTION_MOVE_OPPORTUNITY,
            validate_config=_validate_move_opportunity_config,
            execute=_execute_move_opportunity,
        ),
        WorkflowActionSpec(
            name=ACTION_SEND_EMAIL,
            validate_config=_validate_send_email_config,
            execute=_execute_send_email,
        ),
        WorkflowActionSpec(
            name=ACTION_SEND_WEBHOOK,
            validate_config=_validate_send_webhook_config,
            execute=_execute_send_webhook,
        ),
    ):
        registry.register(spec)
    registry.require_complete()
    return registry


_REGISTRY = _build_registry()


def get_action_registry() -> WorkflowActionRegistry:
    """The process-wide Automation action registry.

    Exposed so a composition root (`product/api/main.py`, the durable
    worker entrypoints) can register an action implementation owned by
    another product domain **without Automation importing that domain** --
    the dependency inversion Phase 10.3A exists to establish. Registration
    is an explicit call made by the composition root, never an import side
    effect of the domain package, so the wiring is visible in one place
    and cannot vary with import order.

    No such foreign action is registered today: `ACTIONS` below declares
    only Automation's own five, so `register()` would reject anything
    else. Phase 10.4A adds its name to that declared vocabulary and wires
    its adapter here; this phase deliberately stops at the seam."""
    return _REGISTRY


def validate_action_config(action_type: str, action_config: Mapping[str, object]) -> None:
    """Structural validation only, at workflow create/update time -- the
    same required-field checks each `_execute_*` performs at execution
    time, run early so a malformed workflow definition is rejected before
    it is ever saved, not discovered the first time it tries to fire.

    Resolves through the registry, but the *vocabulary* check above it
    (`validate_action_type()`) still consults the static `ACTIONS`
    constant -- so whether a given workflow definition is publishable
    never depends on which implementations happen to be registered in this
    process."""
    _REGISTRY.get(action_type).validate_config(action_config)


def execute_action(
    action_type: str,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action_config: Mapping[str, object],
    payload: Mapping[str, object],
) -> dict[str, object]:
    try:
        action = _REGISTRY.get(action_type)
    except UnknownWorkflowActionError as exc:
        # Preserves this function's own pre-10.3A contract exactly:
        # an unresolvable action_type is an AutomationValidationError,
        # which the durable engine already classifies as permanent /
        # non-retryable (`product/automation/durable/business_activities.py`).
        raise AutomationValidationError(f"unknown action_type: {action_type!r}") from exc
    return action.execute(actor_user_id, tenant_id, action_config, payload)


__all__ = [
    "ACTIONS",
    "ACTION_CREATE_TASK",
    "ACTION_MOVE_OPPORTUNITY",
    "ACTION_SEND_EMAIL",
    "ACTION_SEND_WEBHOOK",
    "ACTION_UPDATE_CONTACT",
    "MAX_ACTION_CONFIG_STRING_CHARS",
    "MAX_WEBHOOK_BODY_BYTES",
    "execute_action",
    "get_action_registry",
    "validate_action_config",
    "validate_action_type",
]
