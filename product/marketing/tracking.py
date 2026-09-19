"""Public open/click tracking (docs/ROADMAP.md Phase 6.5).

**Both endpoints this module backs are public and unauthenticated** --
mirrors `product/marketing/forms.py`'s own treatment of the public
form-submission path, with one deliberate difference stated explicitly
below (never a 404, ever, from the pixel endpoint).

`resolve_tracking_token()` looks up `marketing.recipient_tracking_tokens`
(deliberately unscoped -- migration `0023_marketing_tracking`) via a
plain, untenanted `session_scope()` read, exactly mirroring
`product.white_label.domains.resolve_tenant_for_domain()`/
`product.marketing.forms.resolve_form_by_token()`. Once resolved, the
real `campaign_recipients` row is read/written through the ordinary,
correctly-RLS-scoped `tenant_session_scope()` path -- ordinary product
code from that point on, no further exception to the tenant-isolation
discipline.

**`record_open()` never raises for an unknown/invalid token** -- the
tracking-pixel endpoint's whole purpose is to be invisibly embedded in an
email; a 404 response is itself a detectable signal (distinguishing "this
recipient opened the email" from "this token was garbage") that this
endpoint must never leak, stricter than the form-submission 404 case on
purpose. `record_click()` follows the identical reasoning: an unknown
token redirects to the safe fallback, never a 404.

**Open-redirect safety (`resolve_click_target`)**: the redirect target is
always and only the resolved campaign's own server-stored
`click_target_url` column -- this function accepts no caller-supplied URL
of any kind, and never will; there is no parameter here for one. A caller
attempting to pass `?url=`/`?redirect=`/`?next=` on the click endpoint has
no effect at all, because nothing downstream of routing ever reads such a
parameter (see `product/marketing/routes.py`'s own click-endpoint
docstring for the same guarantee stated at the HTTP layer)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from infra.db import session_scope, tenant_session_scope

from product.marketing.models import (
    MarketingCampaign,
    MarketingCampaignRecipient,
    MarketingRecipientTrackingToken,
)

# Never an open-redirect target of unknown provenance -- a fixed,
# same-origin-relative fallback for an unknown/expired tracking token.
# The actual absolute URL a deployment resolves this to is an ordinary
# frontend routing concern, out of this module's scope.
FALLBACK_REDIRECT_PATH = "/"


@dataclass(frozen=True, slots=True)
class ResolvedTrackingToken:
    tenant_id: uuid.UUID
    recipient_id: uuid.UUID


def resolve_tracking_token(tracking_token: str) -> ResolvedTrackingToken | None:
    if not tracking_token:
        return None
    with session_scope() as session:
        row = session.get(MarketingRecipientTrackingToken, tracking_token)
        if row is None:
            return None
        return ResolvedTrackingToken(tenant_id=row.tenant_id, recipient_id=row.recipient_id)


def record_open(tracking_token: str) -> None:
    """Sets `opened_at` only if not already set (first-open wins,
    idempotent). Never raises for an unknown token -- see module
    docstring."""
    resolved = resolve_tracking_token(tracking_token)
    if resolved is None:
        return
    with tenant_session_scope(resolved.tenant_id) as session:
        recipient = session.get(MarketingCampaignRecipient, resolved.recipient_id)
        if recipient is None or recipient.tenant_id != resolved.tenant_id:
            return
        if recipient.opened_at is None:
            recipient.opened_at = datetime.now(UTC)
            session.flush()


def record_click_and_resolve_target(tracking_token: str) -> str:
    """Sets `clicked_at` only if not already set, then returns the
    redirect target -- always and only the recipient's own campaign's
    server-stored `click_target_url`, or `FALLBACK_REDIRECT_PATH` if the
    token is unknown or the campaign has none configured. Never accepts
    or trusts a caller-supplied redirect target (see module docstring)."""
    resolved = resolve_tracking_token(tracking_token)
    if resolved is None:
        return FALLBACK_REDIRECT_PATH
    with tenant_session_scope(resolved.tenant_id) as session:
        recipient = session.get(MarketingCampaignRecipient, resolved.recipient_id)
        if recipient is None or recipient.tenant_id != resolved.tenant_id:
            return FALLBACK_REDIRECT_PATH
        if recipient.clicked_at is None:
            recipient.clicked_at = datetime.now(UTC)
            session.flush()
        campaign = session.get(MarketingCampaign, recipient.campaign_id)
        if campaign is None or not campaign.click_target_url:
            return FALLBACK_REDIRECT_PATH
        return campaign.click_target_url


# A real 1x1 transparent GIF -- the minimal valid byte sequence, served
# as-is by the open-tracking route regardless of whether the token
# resolved (see module docstring).
TRANSPARENT_GIF_BYTES = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"
)
