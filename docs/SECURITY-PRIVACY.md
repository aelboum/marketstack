# Security & Privacy: How This Product Inherits SaaS-OS's Boundaries

Status: PROPOSED. This document maps the brief's security/privacy
requirements onto `saas-os`'s already-Accepted security architecture
(`saas-os` `docs/SECURITY.md`, `docs/MULTI-TENANCY.md`,
`docs/AI-CONTROL-PLANE.md`) and states where this product adds its own
discipline on top.

## Principle (Inherited Unchanged)

`saas-os` `docs/SECURITY.md` §1: "Security-critical code lives in Core/Infra,
not Product. A product cannot weaken the platform's security guarantees; it
can only operate within them." This product never reimplements
authentication, authorization, tenant isolation, or secrets handling — it
consumes SaaS-OS's existing chokepoints for all of these, exactly as
`docs/ARCHITECTURE.md` §1 states.

## Item-by-Item

- **Tenant isolation**: enforced at `infra.db` for every table this product
  defines, the moment it carries `tenant_id` — no new mechanism. Accounting
  and CRM data are ordinary tenant-owned data under this same guarantee; the
  brief's requirement that "accounting data and CRM data must not bypass
  SaaS-OS authorization boundaries" is satisfied by construction as long as
  this product never opens a raw SQLAlchemy/psycopg connection outside
  `infra.db` — enforced in this product's own CI the same way `saas-os`
  enforces it in its own (an import-linter contract forbidding
  `sqlalchemy`/`psycopg` imports outside this product's own equivalent of
  `infra/db` usage, from Phase 1.4 onward).
- **Authorization**: every product-defined permission (e.g.
  `crm:contact.merge`, `accounting:journal_entry.post`) is evaluated through
  `core.rbac.can()` — this product never writes an `if user.role ==
  'admin'` check anywhere. Product-defined permission *names* are this
  product's own (`saas-os` `docs/SECURITY.md` §3 explicitly permits this);
  the evaluator is not.
- **Delegated administration**: see `docs/ARCHITECTURE.md` §3 — fully
  mapped onto `core.rbac`'s existing `SUBTREE` scope, delegation, and
  explicit-deny primitives.
- **Service accounts / machine credentials**: `core.identity
  .create_service_account()` + `core.api_keys` for any client-side
  automation or integration calling this product's API — no second
  credential mechanism.
- **Audit**: every privileged action this product's UI/API exposes (role
  changes, financial-record posting, support-access grants, AI tool
  invocations) is recorded through `core.audit_log`'s existing interface —
  never a second, product-specific audit store. This includes financial
  actions specifically, per the brief's explicit call-out.
- **Secrets**: every credential this product handles (integration API keys,
  webhook signing secrets, tenant-supplied provider credentials) flows
  through `infra.secrets`'s `SecretsProvider` — see `docs/INTEGRATIONS.md`
  §"Credential Handling."
- **Encryption**: `core.crypto`'s application-level field encryption
  (ADR-0019 in `saas-os`) is used for sensitive database-stored values this
  product introduces — accounting identifiers, stored payment/bank
  references, any PII this product deems sensitive beyond ordinary tenant
  data. Transport encryption (DB/Redis TLS) is already handled at the
  infrastructure level (`saas-os` ADR-0021), inherited unchanged.
- **PII / financial data / document access**: classified per `saas-os`
  `docs/SECURITY.md` §9's existing directional categories (tenant business
  data, platform account data, secrets, audit data) — this product's
  accounting and CRM data are "tenant business data," isolated per §5 there.
  A formal, jurisdiction-specific classification/retention policy (Dutch
  bookkeeping retention vs. GDPR erasure, flagged in
  `docs/ACCOUNTING-SCOPE.md`) is a Phase 15 deliverable requiring legal
  review, not assumed here.
- **Data retention / export / deletion**: this product's own tenant-owned
  data participates in `core.tenancy`'s existing tenant-purge orchestration
  by registering a `core.tenancy.purge_participants.TenantPurgeParticipant`
  per module that retains tenant data (`saas-os` `docs/MULTI-TENANCY.md` §6
  — the exact mechanism `examples/reference-consumer/reference_consumer
  /purge.py` already demonstrates). The accounting module's retention
  tension (financial-record retention law vs. tenant erasure) is flagged
  explicitly in `docs/ACCOUNTING-SCOPE.md` and must be resolved (e.g. via an
  anonymizing participant rather than a deleting one, which `saas-os`'s own
  purge-participant contract explicitly permits: "a Product... may instead
  register a participant that anonymizes or otherwise retains its own data
  under a separately documented, deliberately approved retention policy")
  before Phase 15 is considered complete. Individual-identity erasure
  (distinct from tenant purge) reuses `core.identity.erasure
  .erase_user_identity()` unchanged.
- **Exportability**: every module's tenant-owned data must be exportable on
  request (CSV/JSON at minimum) — an explicit acceptance criterion in the
  relevant phase, not an afterthought, particularly for accounting data
  (`docs/ACCOUNTING-SCOPE.md`).
- **Support access**: platform/agency staff troubleshooting a tenant's data
  goes through `core.rbac`'s existing support-access-request workflow —
  time-boxed, approved, audited, revocable. No ad hoc "impersonate tenant"
  backdoor is ever built, regardless of how convenient it would be for
  support tooling.
- **Privileged access**: the same RBAC/audit discipline applies uniformly to
  human staff and to this product's own AI tools — an AI agent is a
  first-class, scoped principal (`saas-os` `docs/SECURITY.md` §3), never a
  bypass.
- **Webhook security**: inbound provider webhooks are signature-verified
  before processing (`docs/INTEGRATIONS.md` §"Webhook Security"); outbound
  webhooks this product might offer to its own tenants (a tenant subscribing
  to this product's events, e.g. "notify my Zapier when a lead is created")
  reuse `core.webhooks`'s existing subscription/delivery/retry/signing
  mechanism directly (Category A) rather than building a second one.
- **Integration credentials**: see `docs/INTEGRATIONS.md` §"Credential
  Handling" — tenant-supplied third-party credentials are encrypted
  (`core.crypto`) and scoped exactly like any other sensitive tenant data;
  cross-tenant visibility (an agency viewing a client's own credential) is
  an explicit product decision at implementation time, not a default.
- **AI access to customer data**: every AI feature this product builds
  passes through the full three-gate boundary `saas-os` already implements
  — Tool Authorization (`control_plane.orchestration`), Data Authorization
  (`control_plane.data_authorization`, ADR-0013), and, if this product ever
  opts into adaptive learning from tenant interactions, Learning
  Authorization (ADR-0014). No AI feature in this product calls an external
  LLM/voice provider directly, bypassing these gates, "even for a narrow or
  temporary use case" — `saas-os` `docs/SECURITY.md` §6.1 rule 8, applied
  here without exception. Financial data specifically is named in that same
  section as a sensitive class never sent to an external AI provider
  without an explicit, reviewed policy decision — relevant the moment any
  AI feature (e.g. an "explain this report" assistant) touches accounting
  data.

## What This Document Does Not Decide

The exact set of product-defined RBAC permission names, the exact retention
periods, and the exact classification of which specific fields count as
"sensitive" beyond the categories above are implementation-time decisions
for the relevant `docs/ROADMAP.md` phase — this document fixes which
SaaS-OS mechanism each decision routes through, not the decision itself.
