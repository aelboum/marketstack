"use client";

// Branding and custom domain.
//
// Both are real product capabilities with real backend groundwork --
// `white_label.tenant_branding` and `white_label.tenant_domains` are
// migrated tables, `DbBrandingProvider.get_branding()` implements the
// documented client -> agency -> platform fallback chain, and
// `DomainResolutionMiddleware` already resolves a custom host to its
// tenant. None of it is reachable from a browser: `product/white_label/`
// ships no `routes.py`, `product/api/main.py` mounts no white-label
// router, and there is no write path at any layer (no `set_branding()`,
// no domain create/delete -- only `get_branding()`,
// `resolve_tenant_for_domain()`, and a purge participant that deletes).
//
// So this page renders no branding form. A form here could not save, and
// storing values in the browser would be exactly the "frontend-only
// branding persistence that pretends to be durable" UI-7 forbids. The
// missing contract is stated instead, and carried in UI-7's report.
import { SettingsSection } from "./SettingsShell";
import { UnavailableCapability } from "./UnavailableCapability";

export function BrandingSettingsPanel() {
  return (
    <>
      <SettingsSection
        title="Branding"
        description="How this workspace presents itself — name, logo, and colors."
      >
        <UnavailableCapability
          title="Workspace branding"
          summary="Set the display name, logo, favicon, colors, typography, and the sender identity used on outgoing email."
          whatExistsToday="The backend already stores branding per tenant and resolves it through a client → agency → platform fallback chain, so a tenant with no branding of its own inherits its agency's. Today that resolution is read-only and server-side: nothing exposes it to this application, and nothing can write it."
          missingContract={[
            "GET /v1/white-label/tenants/{tenant_id}/branding — read the resolved branding (white_label.branding.Branding already defines the shape: display_name, logo_asset_ref, favicon_asset_ref, color_primary, color_secondary, color_accent, typography, email_from_name, email_reply_to, support_contact, legal_terms_url, legal_privacy_url, source_tenant_id)",
            "PUT/PATCH /v1/white-label/tenants/{tenant_id}/branding — write it (no service-layer write function exists yet either)",
            "product/white_label/permissions.py — the module has no permissions chokepoint, unlike every other product module",
            "An asset upload path for logo_asset_ref/favicon_asset_ref (product/foundation/storage.py defines an ObjectStorage protocol with an in-memory fake only — no real adapter)",
          ]}
        />
      </SettingsSection>

      <SettingsSection
        title="Custom domain"
        description="Serve this workspace from your own hostname."
      >
        <UnavailableCapability
          title="Custom domain"
          summary="Point your own hostname at this workspace and have requests resolve to it."
          whatExistsToday="Host-to-tenant resolution already runs on every request, and a tenant_domains table exists. There is no way to add, list, or remove a domain: no endpoint, and no service function either. TLS provisioning is explicitly out of scope for the backend phase that introduced this, so this UI must not imply a certificate would be issued."
          missingContract={[
            "GET /v1/white-label/tenants/{tenant_id}/domains — list configured domains (white_label.models.TenantDomain: domain, tenant_id, tls_status, created_at)",
            "POST /v1/white-label/tenants/{tenant_id}/domains — add one (no create function exists at the service layer)",
            "DELETE /v1/white-label/tenants/{tenant_id}/domains/{domain} — remove one",
            "Verification of domain ownership before a hostname is accepted — tenant_domains is deliberately not RLS-scoped, so this endpoint would be the only guard",
          ]}
        />
      </SettingsSection>
    </>
  );
}
