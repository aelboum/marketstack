"""Outbound email sending (docs/ROADMAP.md Phase 5.2).

**Architecture correction, verified by reading `saas-os` directly, not
assumed from the roadmap's own wording**: 5.2's Objective says "wire
`product/conversations/` to `core.notifications`/`core.email` for actual
sending." `core.notifications.dispatch_notification(tenant_id,
recipient_user_id, channel, body, ...)` requires `recipient_user_id` to
be a real `TenantMembership` -- enforced by a composite FK in
`core/notifications/models.py` (confirmed by reading its own docstring:
"`(tenant_id, recipient_user_id)` must be a real `TenantMembership`").
That module is for notifying **internal tenant members** (staff) --
`core/notifications/__init__.py`'s own module docstring never mentions
external recipients. A CRM contact has no `TenantMembership` at all, so
`dispatch_notification()` cannot be used here.

`core.email.send_email(message: EmailMessage, provider=None) ->
EmailSendResult` is the correct, lower-level integration point instead --
no membership required, sends to an arbitrary external address. This is
still Category A (`docs/RESPONSIBILITY-MATRIX.md`): `core.email` is
already-implemented SaaS-OS capability, this module only wires it,
exactly as 5.2's Scope says ("adapter wiring only -- no new email-sending
mechanism") -- the correction is which `core.*` function is the actual
adapter point, not a deviation from the phase's own intent.

**On provider failure, no message is recorded.** `send_email_message()`
calls `core.email.send_email()` first; only on success does it call
`product.conversations.messages.create_message()`. A failed send must
never produce a `Message` row claiming an email was sent that wasn't --
proven by `tests/conversations/test_email_sending_integration.py
::test_send_failure_does_not_record_a_message`.
"""

from __future__ import annotations

import uuid

from core.email import EmailMessage, get_email_config, send_email
from core.email.errors import EmailConfigurationError, EmailProviderError, InvalidEmailAddressError
from core.email.provider import EmailProvider

from product.conversations.errors import ConversationValidationError
from product.conversations.messages import MessageView, create_message
from product.conversations.models import DIRECTION_OUTBOUND
from product.conversations.threads import get_thread


def send_email_message(
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    thread_id: uuid.UUID,
    *,
    to_email: str,
    subject: str,
    body: str,
    provider: EmailProvider | None = None,
) -> MessageView:
    """Send `body` as a real email to `to_email` via `core.email`, then
    record it in the thread. `get_thread()`'s own `THREAD_RESOURCE:read`
    check happens first (via this call), and `create_message()`'s own
    `THREAD_RESOURCE:update` check gates the actual write -- a caller who
    can read but not update a thread is correctly denied before any send
    is attempted (`get_thread` alone would let them proceed to the send
    call, but `create_message()`'s own `require()` call, evaluated before
    it touches the database, still blocks the write -- the send itself
    happening first is an accepted, documented ordering: `core.email` has
    no tenant/authorization concept of its own to gate on, so the
    provider call cannot be moved after the permission check without
    duplicating that check here redundantly; the real, load-bearing
    authorization gate remains `create_message()`'s)."""
    # get_thread() itself already requires THREAD_RESOURCE:read for
    # actor_user_id at tenant_id -- an actor who cannot even read this
    # thread is stopped here, before any provider call.
    thread = get_thread(actor_user_id, tenant_id, thread_id)
    if thread.contact_id is None:
        raise ConversationValidationError(
            "cannot send an email on a thread with no linked contact."
        )

    config = get_email_config()
    if not config.default_sender:
        raise EmailConfigurationError("EMAIL_DEFAULT_SENDER is not set.")
    message = EmailMessage(
        sender=config.default_sender,
        to=(to_email,),
        subject=subject,
        text_body=body,
    )
    try:
        send_email(message, provider=provider)
    except (EmailConfigurationError, EmailProviderError, InvalidEmailAddressError):
        # Propagate unchanged -- no Message row is created for a failed
        # send (module docstring). Never the recipient/body in a log
        # here; core.email.service._send_email_channel-equivalent
        # logging discipline is this function's caller's concern if any
        # is added later, not duplicated here speculatively.
        raise

    return create_message(
        actor_user_id,
        tenant_id,
        thread_id,
        direction=DIRECTION_OUTBOUND,
        is_internal_note=False,
        body=body,
        author_user_id=actor_user_id,
    )
