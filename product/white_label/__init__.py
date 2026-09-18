"""White-label branding: per-tenant/per-agency logo, colors, custom
domain, login/email/notification branding. See docs/WHITE-LABEL.md.
`branding.py` is the BrandingProvider interface + fallback-chain
resolution (Phase 2.3); `domains.py` is custom-domain -> tenant_id
resolution (Phase 2.4). Mirrors SaaS-OS's own provider-abstraction
pattern, so BrandingProvider could be proposed upstream later if a
second product needs it."""
