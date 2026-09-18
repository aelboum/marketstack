"""The `BrandingProvider` interface and its resolution logic
(docs/ROADMAP.md Phase 2.3; docs/WHITE-LABEL.md sections 1 and 4).

Mirrors `core/billing/provider.py`'s exact Protocol+adapter pattern:
`BrandingProvider` is the only vocabulary any later module needs
("every module that needs to render tenant-facing UI... calls this
interface -- never reads white_label.tenant_branding directly",
docs/WHITE-LABEL.md section 4). `DbBrandingProvider` is this phase's
one concrete implementation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.tenancy import get_ancestor_chain, get_tenant
from infra.db import tenant_session_scope

from product.white_label.models import TenantBranding

# Deliberately where the eventual commercial name would live
# (docs/ADR/0001-naming-and-identifier-neutrality.md) -- never
# "MarketStack" or any variant of the temporary working name, never
# hardcoded anywhere else in this codebase. A single code-level constant,
# not a database row (docs/WHITE-LABEL.md section 1, "Platform default
# branding... a single configuration row").
PLATFORM_DEFAULT_BRANDING_DISPLAY_NAME = "Product"


@dataclass(frozen=True, slots=True)
class Branding:
    """The resolved branding for a tenant. `source_tenant_id` records
    which tenant's own row actually supplied this branding -- the
    requested `tenant_id` itself, an ancestor it inherited from, or
    `None` when nothing in the chain had a row and the platform default
    applies (there is no tenant that "owns" the platform default)."""

    display_name: str
    logo_asset_ref: str | None
    favicon_asset_ref: str | None
    color_primary: str | None
    color_secondary: str | None
    color_accent: str | None
    typography: str | None
    login_branding_overrides: str | None
    email_from_name: str | None
    email_reply_to: str | None
    support_contact: str | None
    legal_terms_url: str | None
    legal_privacy_url: str | None
    source_tenant_id: uuid.UUID | None


def _platform_default_branding() -> Branding:
    return Branding(
        display_name=PLATFORM_DEFAULT_BRANDING_DISPLAY_NAME,
        logo_asset_ref=None,
        favicon_asset_ref=None,
        color_primary=None,
        color_secondary=None,
        color_accent=None,
        typography=None,
        login_branding_overrides=None,
        email_from_name=None,
        email_reply_to=None,
        support_contact=None,
        legal_terms_url=None,
        legal_privacy_url=None,
        source_tenant_id=None,
    )


def _branding_from_row(row: TenantBranding) -> Branding:
    return Branding(
        display_name=row.display_name,
        logo_asset_ref=row.logo_asset_ref,
        favicon_asset_ref=row.favicon_asset_ref,
        color_primary=row.color_primary,
        color_secondary=row.color_secondary,
        color_accent=row.color_accent,
        typography=row.typography,
        login_branding_overrides=row.login_branding_overrides,
        email_from_name=row.email_from_name,
        email_reply_to=row.email_reply_to,
        support_contact=row.support_contact,
        legal_terms_url=row.legal_terms_url,
        legal_privacy_url=row.legal_privacy_url,
        source_tenant_id=row.tenant_id,
    )


@runtime_checkable
class BrandingProvider(Protocol):
    """docs/WHITE-LABEL.md section 4. Every module that needs to render
    tenant-facing UI, compose a tenant-facing email, or produce a
    tenant-facing PDF calls this -- never reads
    `white_label.tenant_branding` directly."""

    def get_branding(self, tenant_id: uuid.UUID) -> Branding:
        """Resolve `tenant_id`'s branding via the fallback chain (client
        -> agency -> platform default). Raises `core.tenancy
        .TenantNotFoundError` for an unrecognized `tenant_id` -- fails
        closed, never falls through to the platform default for a
        tenant id that does not exist (docs/ROADMAP.md Phase 2.3: "fail-
        closed on an unrecognized/malformed tenant id; no default-tenant
        fallback"). A *valid* tenant with no customization anywhere in
        its own chain correctly resolves to the platform default -- that
        is the intended, normal case, not a failure."""
        ...


class DbBrandingProvider:
    """The one concrete `BrandingProvider` implementation this phase
    ships, reading `white_label.tenant_branding`."""

    def get_branding(self, tenant_id: uuid.UUID) -> Branding:
        # Fails closed: raises TenantNotFoundError for an unknown
        # tenant_id, before any branding lookup is attempted.
        get_tenant(tenant_id)

        candidate_ids = [tenant_id, *get_ancestor_chain(tenant_id)]
        for candidate_id in candidate_ids:
            # A fresh, individually RLS-scoped session per candidate --
            # never one session reused across different tenant_ids, and
            # never an unscoped session with a manual WHERE tenant_id=...
            # filter. tenant_session_scope() only sets a Postgres session
            # variable (infra/db/session.py's own docstring: it performs
            # no actor/authorization check itself), so reading each
            # ancestor's own row through that ancestor's own scoped
            # session is the sanctioned way to do this hierarchy-aware
            # read -- exactly analogous to how core.usage's own
            # hierarchy-aware aggregation and billing-owner resolution
            # read across tenant boundaries elsewhere in saas-os.
            with tenant_session_scope(candidate_id) as session:
                row = session.get(TenantBranding, candidate_id)
                if row is not None:
                    return _branding_from_row(row)

        return _platform_default_branding()
