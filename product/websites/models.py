"""ORM models for the `websites` schema (docs/ROADMAP.md Phase 11.1).

Declared on the installed `saas-os` package's shared `infra.db` base and
primitives, exactly like every other `product/*/models.py` -- this
module never imports `sqlalchemy` directly.

**`Website` is deliberately NOT RLS-scoped** -- mirrors
`product/telephony/models.py::PhoneNumber`/`product/appointments/models.py
::BookingLink`'s identical precedent and reasoning: an anonymous visitor's
request for a published page carries only the website's own public
`slug`, and resolving that slug to a tenant must happen *before* any
tenant context exists. Putting `slug` on an RLS-protected table would
make it unresolvable by that untenanted lookup -- RLS would simply return
zero rows, the exact mistake `PhoneNumber`/`BookingLink` already avoid.
`Website.slug` therefore carries a real, standalone `UNIQUE` constraint
(global, not composite with `tenant_id`) -- unlike a phone number, a
website slug is chosen by the tenant, not assigned by a provider, but the
same structural requirement applies: the public lookup key must be
resolvable with no tenant context, so it cannot be scoped by the tenant
context it is used to establish. `Website` still carries
`UniqueConstraint(tenant_id, id)` (needed for `Page`'s own composite FK)
even without RLS -- RLS is a Postgres policy layered on top of a table,
structurally independent of whether a composite-FK target unique index
exists. Authenticated CRUD on `Website` filters explicitly by
`tenant_id` at the service layer (`product/websites/websites.py`), the
same discipline `product/telephony/purge.py::TelephonyUnscopedDataPurgeParticipant`
and `product/appointments/calendars.py::get_or_create_booking_link()`
already establish for their own unscoped tables.

**`custom_domain` is a bounded, nullable, globally-unique string field
only** -- no DNS resolution, no TLS provisioning, no ingress wiring. This
phase establishes the domain *state*, not domain *infrastructure*
(docs/ROADMAP.md Phase 2.4's own "TLS provisioning automation is out of
scope... may start as a manual operational step" precedent, applied here
identically). `product/white_label/domains.py::DomainResolutionMiddleware`
resolves a custom domain to a *tenant* for this product's own dashboard;
it is a structurally separate concern from resolving a domain to a
*published website*, and this phase does not wire the two together --
see this module's own package docstring.

**`Page` is ordinary RLS-scoped, tenant-owned data**, reached only after
`Website` lookup has already established `tenant_id` -- exactly
`PhoneNumber`'s own relationship to `PhoneNumberRoutingTarget`/`Call`.
`Page.slug` is unique only *within* its own website
(`UniqueConstraint(tenant_id, website_id, slug)`) -- once the website is
resolved, no further untenanted lookup is needed, so page slugs need no
global uniqueness.

**Draft vs. published content, two separate JSON columns on the same
row** -- `content_blocks` is the page's current, editable draft;
`published_content_blocks` is a snapshot taken at publish time, `None`
until the first publish. The public read path
(`product/websites/pages.py::get_published_page()`) reads
`published_content_blocks` exclusively, never `content_blocks` -- an
in-progress draft edit can never leak publicly before an explicit
publish, and unpublishing (`status` back to `draft`) hides the page
without discarding the last-known-good published snapshot. Both columns
are bounded JSON (a closed, typed block vocabulary validated by
`product/websites/content_blocks.py` before ever reaching this table,
never an unrestricted blob) -- mirrors
`product/automation/durable/models.py::WorkflowVersion.steps`'s own
"bounded JSON, never unbounded blobs" convention.

**Composite-FK discipline**, mirroring every other product module's
models exactly: `Page`'s reference to `Website` is a `ForeignKeyConstraint`
against `Website`'s own `UniqueConstraint(tenant_id, id)`, never a bare
`ForeignKey` on the id column alone -- structurally impossible for a page
row to reference another tenant's website.

**Deletion behavior**: `pages.website_id` is `ON DELETE CASCADE` -- a
page has no meaning without its own website, the same reasoning
`appointments.availability_rules.calendar_id`/`telephony
.phone_number_routing_targets.phone_number_id` already established for
their own parent entities.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from infra.db import (
    JSON,
    Base,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Mapped,
    String,
    UniqueConstraint,
    mapped_column,
    now,
)

MAX_WEBSITE_NAME_LENGTH = 255
MAX_SLUG_LENGTH = 63
MAX_CUSTOM_DOMAIN_LENGTH = 255
MAX_PAGE_TITLE_LENGTH = 255
MAX_LEAD_NAME_LENGTH = 255
MAX_LEAD_EMAIL_LENGTH = 255
MAX_LEAD_PHONE_LENGTH = 32
MAX_LEAD_MESSAGE_LENGTH = 2000

STATUS_DRAFT = "draft"
STATUS_PUBLISHED = "published"
PAGE_STATUSES = (STATUS_DRAFT, STATUS_PUBLISHED)


class Website(Base):
    """A tenant's own website -- the public root a page's slug is
    resolved against. Deliberately NOT RLS-scoped; see module docstring."""

    __tablename__ = "websites"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_websites_websites_id_tenant_id"),
        UniqueConstraint("tenant_id", "id", name="uq_websites_websites_tenant_id_id"),
        UniqueConstraint("slug", name="uq_websites_websites_slug"),
        UniqueConstraint("custom_domain", name="uq_websites_websites_custom_domain"),
        Index("ix_websites_websites_tenant_id", "tenant_id"),
        {"schema": "websites"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("core.tenants.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(MAX_SLUG_LENGTH), nullable=False)
    name: Mapped[str] = mapped_column(String(MAX_WEBSITE_NAME_LENGTH), nullable=False)
    custom_domain: Mapped[str | None] = mapped_column(String(MAX_CUSTOM_DOMAIN_LENGTH))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class Page(Base):
    """One page within a tenant's own website. Ordinary RLS-scoped,
    tenant-owned data; see module docstring for the draft/published
    content split."""

    __tablename__ = "pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "website_id"],
            ["websites.websites.tenant_id", "websites.websites.id"],
            name="fk_websites_pages_tenant_website",
            ondelete="CASCADE",
        ),
        # docs/ROADMAP.md Phase 22: added so `LeadSubmission.page_id` can
        # composite-FK against this table -- `Page` was never itself a
        # composite-FK target before Phase 22 (nothing referenced it), so
        # this constraint did not exist until now (migration
        # `0050_create_websites_lead_submissions_table`).
        UniqueConstraint("tenant_id", "id", name="uq_websites_pages_tenant_id_id"),
        UniqueConstraint(
            "tenant_id", "website_id", "slug", name="uq_websites_pages_tenant_website_slug"
        ),
        Index("ix_websites_pages_tenant_id", "tenant_id"),
        Index("ix_websites_pages_website_id", "website_id"),
        {"schema": "websites"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(String(MAX_SLUG_LENGTH), nullable=False)
    title: Mapped[str] = mapped_column(String(MAX_PAGE_TITLE_LENGTH), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUS_DRAFT)
    content_blocks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    published_content_blocks: Mapped[list | None] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("core.users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now(), onupdate=now()
    )


class LeadSubmission(Base):
    """A lead captured through a published page's own lead-capture form
    (docs/ROADMAP.md Phase 22). Ordinary RLS-scoped, tenant-owned data,
    reached only after `Website`/`Page` lookup has already established
    `tenant_id` -- exactly `Page`'s own relationship to `Website`.

    `contact_id` is the real `crm.contacts` row
    `product/websites/leads.py::capture_lead()` finds-or-creates via
    `product.crm.contacts.create_or_update_contact_from_trusted_source()`
    (`docs/ADR/0015-websites-depends-on-crm.md`) -- **column-scoped**
    `ON DELETE SET NULL (contact_id)`, mirroring
    `product/appointments/models.py::Appointment.contact_id`'s identical,
    correct shape (never a bare `SET NULL`, which would null every column
    in the composite FK including the `NOT NULL` `tenant_id`): deleting a
    contact must not destroy the lead-submission record, only unlink it.

    `first_name`/`last_name`/`email`/`phone`/`message` are the raw
    submitted values, kept here (not only inside the CRM contact) so a
    submission's own original context survives even if the linked
    contact's fields are later edited by staff -- mirrors
    `product/marketing/models.py::MarketingFormSubmission.submitted_data`'s
    identical "the submission is its own historical record" reasoning.
    `message` is free text, bounded (`MAX_LEAD_MESSAGE_LENGTH`), never an
    unrestricted blob.
    """

    __tablename__ = "lead_submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "website_id"],
            ["websites.websites.tenant_id", "websites.websites.id"],
            name="fk_websites_lead_submissions_tenant_website",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "page_id"],
            ["websites.pages.tenant_id", "websites.pages.id"],
            name="fk_websites_lead_submissions_tenant_page",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"],
            ["crm.contacts.tenant_id", "crm.contacts.id"],
            name="fk_websites_lead_submissions_tenant_contact",
            ondelete="SET NULL (contact_id)",
        ),
        Index("ix_websites_lead_submissions_tenant_id", "tenant_id"),
        Index("ix_websites_lead_submissions_website_id", "website_id"),
        Index("ix_websites_lead_submissions_page_id", "page_id"),
        Index("ix_websites_lead_submissions_contact_id", "contact_id"),
        {"schema": "websites"},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    website_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    page_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    first_name: Mapped[str] = mapped_column(String(MAX_LEAD_NAME_LENGTH), nullable=False)
    last_name: Mapped[str] = mapped_column(String(MAX_LEAD_NAME_LENGTH), nullable=False)
    email: Mapped[str] = mapped_column(String(MAX_LEAD_EMAIL_LENGTH), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(MAX_LEAD_PHONE_LENGTH), nullable=True)
    message: Mapped[str | None] = mapped_column(String(MAX_LEAD_MESSAGE_LENGTH), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=now()
    )


__all__ = [
    "MAX_CUSTOM_DOMAIN_LENGTH",
    "MAX_LEAD_EMAIL_LENGTH",
    "MAX_LEAD_MESSAGE_LENGTH",
    "MAX_LEAD_NAME_LENGTH",
    "MAX_LEAD_PHONE_LENGTH",
    "MAX_PAGE_TITLE_LENGTH",
    "MAX_SLUG_LENGTH",
    "MAX_WEBSITE_NAME_LENGTH",
    "PAGE_STATUSES",
    "STATUS_DRAFT",
    "STATUS_PUBLISHED",
    "LeadSubmission",
    "Page",
    "Website",
]
