"""ORM models for the `marketing` schema (docs/ROADMAP.md Phase 6.1-6.2).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like `product/crm/models.py`/`product/conversations
/models.py` -- this module never imports `sqlalchemy` directly.

**Tenancy**: every table here is owned by the **client tenant** (the same
tenant CRM/Conversations data lives in) -- a client's own marketing
campaigns and suppression list are that client's own business data, for
the identical reason `crm.*`/`conversations.*` data is. An agency reaches
a client's marketing data via inherited `SUBTREE` role, `get_current_actor`
+ service-layer `core.rbac.can()`, never `get_tenant_context()` -- see
`docs/ADR/0002-...`'s Phase 4 addendum, which applies unchanged here. No
new tenancy concept.

**Composite-FK discipline**, mirroring `product/crm/models.py` exactly:
`MarketingCampaignRecipient.campaign_id` is a `ForeignKeyConstraint`
against `marketing.campaigns(tenant_id, id)`; `.contact_id` and
`MarketingSuppression.contact_id` are the identical pattern against
`crm.contacts(tenant_id, id)` -- structurally impossible for a row here to
reference another tenant's campaign or contact.

**Deletion behavior** (deliberate, documented, mirrors
`conversations.threads.contact_id`'s own reasoning -- and specifically
NOT `crm.contacts.company_id`'s original, buggy shape):
- `campaigns` has no parent to cascade from (it is the root of this
  schema).
- `campaign_recipients.campaign_id` is `ON DELETE CASCADE` -- a recipient
  row has no meaning without its campaign, the same reasoning
  `crm.tasks`/`crm.notes` already established for their own parent
  entities.
- `campaign_recipients.contact_id` is `ON DELETE SET NULL (contact_id)`
  -- **column-scoped**, not bare `SET NULL`. This is the exact fix for
  the defect class the deferred Phase 4 CRM bug demonstrated (bare
  `SET NULL` on a multi-column FK nulls every column in the FK,
  including the `NOT NULL` `tenant_id`, causing a `NotNullViolation`
  instead of unlinking) -- deleting a contact must not destroy campaign
  send history, only unlink it, and this table gets that right from the
  start rather than repeating the mistake.
- `suppressions.contact_id` is `ON DELETE CASCADE` -- a suppression
  record has no independent meaning once the contact itself is gone.
  **Open question, not decided here**: whether suppression should
  instead persist by email address, independent of the CRM contact
  record, so that re-importing/re-creating a contact with the same email
  does not silently lose a prior unsubscribe -- a real compliance
  consideration, deferred to Phase 18's dedicated Dutch/GDPR compliance
  review, not resolved in this phase.

`assigned_to_user_id`-shaped columns do not appear in this schema (no
per-campaign "owner" concept exists yet, unlike `conversations.threads
.assigned_to_user_id` -- not a gap, simply not part of 6.1/6.2's literal
scope).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    Base,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Mapped,
    String,
    Text,
    UniqueConstraint,
    mapped_column,
    now,
)

FIELD_TYPE_TEXT = "text"
FIELD_TYPE_EMAIL = "email"
FIELD_TYPE_PHONE = "phone"
VALID_FORM_FIELD_TYPES = (FIELD_TYPE_TEXT, FIELD_TYPE_EMAIL, FIELD_TYPE_PHONE)

TEMPLATE_TYPE_EMAIL_CAMPAIGN = "email_campaign"
TEMPLATE_TYPE_SMS_CAMPAIGN = "sms_campaign"
TEMPLATE_TYPE_LANDING_PAGE = "landing_page"
VALID_TEMPLATE_TYPES = (
    TEMPLATE_TYPE_EMAIL_CAMPAIGN,
    TEMPLATE_TYPE_SMS_CAMPAIGN,
    TEMPLATE_TYPE_LANDING_PAGE,
)

MAX_FORM_NAME_LENGTH = 255
MAX_FORM_FIELD_VALUE_LENGTH = 2_000
MAX_TEMPLATE_NAME_LENGTH = 255
MAX_TEMPLATE_CONTENT_LENGTH = 50_000
MAX_CLICK_TARGET_URL_LENGTH = 2048

CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
VALID_CHANNELS = (CHANNEL_EMAIL, CHANNEL_SMS)

STATUS_DRAFT = "draft"
STATUS_SENDING = "sending"
STATUS_SENT = "sent"
STATUS_CANCELLED = "cancelled"
STATUS_FAILED = "failed"
VALID_CAMPAIGN_STATUSES = (
    STATUS_DRAFT,
    STATUS_SENDING,
    STATUS_SENT,
    STATUS_CANCELLED,
    STATUS_FAILED,
)

RECIPIENT_STATUS_PENDING = "pending"
RECIPIENT_STATUS_SENT = "sent"
RECIPIENT_STATUS_SUPPRESSED = "suppressed"
RECIPIENT_STATUS_FAILED = "failed"
VALID_RECIPIENT_STATUSES = (
    RECIPIENT_STATUS_PENDING,
    RECIPIENT_STATUS_SENT,
    RECIPIENT_STATUS_SUPPRESSED,
    RECIPIENT_STATUS_FAILED,
)

SUPPRESSION_REASON_UNSUBSCRIBED = "unsubscribed"
SUPPRESSION_REASON_BOUNCED = "bounced"
SUPPRESSION_REASON_COMPLAINED = "complained"
SUPPRESSION_REASON_MANUAL = "manual"
VALID_SUPPRESSION_REASONS = (
    SUPPRESSION_REASON_UNSUBSCRIBED,
    SUPPRESSION_REASON_BOUNCED,
    SUPPRESSION_REASON_COMPLAINED,
    SUPPRESSION_REASON_MANUAL,
)

# Bounds enforced at the service/API layer (product/marketing/campaigns.py,
# routes.py's own Pydantic max_length) -- real bounds, not DB CHECKs,
# mirroring how crm.*/conversations.* bound caller input at those same two
# layers.
MAX_CAMPAIGN_NAME_LENGTH = 255
MAX_CAMPAIGN_SUBJECT_LENGTH = 255
MAX_CAMPAIGN_BODY_LENGTH = 50_000  # generous for an HTML/text email/SMS body; still bounded.


class MarketingCampaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_campaigns_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "template_id"],
            ["marketing.templates.tenant_id", "marketing.templates.id"],
            name="fk_marketing_campaigns_tenant_template",
            # Column-scoped SET NULL -- see migration 0022's own docstring
            # and campaigns.py's "one-time copy-in, not a live reference"
            # semantics decision.
            ondelete="SET NULL (template_id)",
        ),
        Index("ix_marketing_campaigns_tenant_id", "tenant_id"),
        Index("ix_marketing_campaigns_template_id", "template_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_CAMPAIGN_NAME_LENGTH), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_DRAFT)
    subject: Mapped[str | None] = mapped_column(String(MAX_CAMPAIGN_SUBJECT_LENGTH), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Small, explicit, code-controlled JSON shape -- never raw SQL, never a
    # free-form query language. See product/marketing/segmentation.py's own
    # module docstring for the exact shape and the injection-safety
    # discipline it follows (identical to product/crm/search.py's own).
    segment_query: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # Phase 6.4: nullable, one-time copy-in source at creation -- never a
    # live reference re-read at send time (product/marketing/campaigns.py).
    template_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    # Phase 6.5: the ONE call-to-action URL this campaign's tracked click
    # link points to -- validated http/https-only at the service layer.
    click_target_url: Mapped[str | None] = mapped_column(
        String(MAX_CLICK_TARGET_URL_LENGTH), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class MarketingSuppression(Base):
    __tablename__ = "suppressions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_suppressions_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "contact_id", "channel", name="uq_marketing_suppressions_contact_channel"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_suppressions_tenant_contact",
            ondelete="CASCADE",
        ),
        Index("ix_marketing_suppressions_tenant_id", "tenant_id"),
        Index("ix_marketing_suppressions_contact_id", "contact_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class MarketingCampaignRecipient(Base):
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_campaign_recipients_tenant_id_id"),
        UniqueConstraint(
            "campaign_id", "contact_id", name="uq_marketing_campaign_recipients_campaign_contact"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["marketing.campaigns.tenant_id", "marketing.campaigns.id"],
            name="fk_marketing_campaign_recipients_tenant_campaign",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_campaign_recipients_tenant_contact",
            # Column-scoped SET NULL -- see module docstring's "Deletion
            # behavior" section. This is the fix for the defect class the
            # deferred Phase 4 CRM bug demonstrated (bare multi-column
            # SET NULL nulls tenant_id too, which is NOT NULL here).
            ondelete="SET NULL (contact_id)",
        ),
        Index("ix_marketing_campaign_recipients_tenant_id", "tenant_id"),
        Index("ix_marketing_campaign_recipients_campaign_id", "campaign_id"),
        Index("ix_marketing_campaign_recipients_contact_id", "contact_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    campaign_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RECIPIENT_STATUS_PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A short failure-category label -- never a full exception message,
    # never PII (mirrors crm.import_jobs.error_report's own discipline of
    # keeping failure detail bounded and non-sensitive).
    error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Phase 6.5: set once, first-open/first-click wins (idempotent -- a
    # real email client typically fetches a tracking pixel more than
    # once). The public lookup that reaches these columns resolves via
    # marketing.recipient_tracking_tokens (a separate, unscoped table --
    # see migration 0023's own docstring for why this column is NOT
    # itself the public lookup key).
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class MarketingForm(Base):
    """Phase 6.3. Deliberately NOT RLS-scoped -- see migration
    `0020_marketing_forms`'s own docstring (mirrors
    `white_label.tenant_domains`'s established precedent exactly).
    `form_token` carries its own, separate global `UniqueConstraint` --
    it is the public lookup key `tenant_id` is resolved *from*, so it
    cannot itself be scoped by the tenant it resolves."""

    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_forms_tenant_id_id"),
        UniqueConstraint("form_token", name="uq_marketing_forms_form_token"),
        Index("ix_marketing_forms_tenant_id", "tenant_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_FORM_NAME_LENGTH), nullable=False)
    form_token: Mapped[str] = mapped_column(String(64), nullable=False)
    # A small, fixed JSON shape (list of {"name", "field_type", "required"})
    # -- see product/marketing/forms.py's own module docstring.
    field_definitions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class MarketingFormSubmission(Base):
    """Phase 6.3. An ordinary, RLS-scoped tenant-owned table (only the
    initial form-token lookup, on `MarketingForm`, needs to happen before
    a tenant context exists -- a submission record itself does not).
    `submitted_data` is new PII storage; treated with the same care as
    every other personal-data column in this product (tenant-scoped,
    RLS-protected, never in audit metadata)."""

    __tablename__ = "form_submissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_form_submissions_tenant_id_id"),
        ForeignKeyConstraint(
            ["tenant_id", "form_id"],
            ["marketing.forms.tenant_id", "marketing.forms.id"],
            name="fk_marketing_form_submissions_tenant_form",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_marketing_form_submissions_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        Index("ix_marketing_form_submissions_tenant_id", "tenant_id"),
        Index("ix_marketing_form_submissions_form_id", "form_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    form_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    submitted_data: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


class MarketingTemplate(Base):
    """Phase 6.4. `template_type="landing_page"` is a stored content blob
    only -- NOT a page builder or rendering engine (Phase 11 owns that).
    Ordinary RLS-scoped tenant-owned table."""

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_marketing_templates_tenant_id_id"),
        UniqueConstraint("tenant_id", "name", name="uq_marketing_templates_tenant_name"),
        Index("ix_marketing_templates_tenant_id", "tenant_id"),
        {"schema": "marketing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_TEMPLATE_NAME_LENGTH), nullable=False)
    template_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class MarketingRecipientTrackingToken(Base):
    """Phase 6.5. Deliberately NOT RLS-scoped, mirroring `MarketingForm`
    exactly -- see migration `0023_marketing_tracking`'s own docstring for
    why this is a separate table rather than a `tracking_token` column on
    the RLS-protected `MarketingCampaignRecipient` itself. Resolved via a
    plain `session_scope()` read by the public tracking pixel/click
    endpoints (`product/marketing/routes.py`), which then read/write the
    real recipient row through the ordinary, correctly-scoped
    `tenant_session_scope()` path."""

    __tablename__ = "recipient_tracking_tokens"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "recipient_id"],
            ["marketing.campaign_recipients.tenant_id", "marketing.campaign_recipients.id"],
            name="fk_marketing_recipient_tracking_tokens_tenant_recipient",
            ondelete="CASCADE",
        ),
        Index("ix_marketing_recipient_tracking_tokens_recipient_id", "recipient_id"),
        {"schema": "marketing"},
    )

    tracking_token: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    recipient_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
