# Product vs. SaaS-OS Responsibility Matrix

Status: PROPOSED — this is the analytical basis for `docs/ROADMAP.md` and for
keeping `saas-os` free of product-specific functionality. Every capability
area named in the product brief is categorized here as one of:

- **A — Already provided by SaaS-OS.** Consume directly, do not rebuild.
- **B — Generic gap in SaaS-OS.** A real capability SaaS-OS should eventually
  have (domain-agnostic, useful to any future product), currently missing.
  Built inside this product for now (interim), with a clean interface that
  makes a future upstream donation possible without a rewrite. **Never
  implemented by editing `saas-os` directly as part of this product's work.**
- **C — Product-specific.** Belongs in this product's own repository,
  permanently. Not a SaaS-OS concern at any point.
- **D — External integration.** A third-party provider, wrapped in an
  adapter this product owns.

This table is the answer to the brief's "Critical roadmap requirement": for
every capability, which category and why.

## Tenancy, Identity, Authorization

| Capability | Category | Reasoning |
|---|---|---|
| Tenant entity, lifecycle (pending/active/suspended/deleted/purged) | A | `core.tenancy` — fully implemented (`saas-os` roadmap Phase 3.1) |
| Tenant hierarchy (agency → client) | A | `core.tenancy.models.Tenant.parent_id` + `core.tenant_ancestry` — fully implemented, structural |
| Delegated administration (subtree-scoped roles) | A | `core.rbac` `RoleScope.SUBTREE` — fully implemented |
| Explicit deny | A | `core.rbac.create_deny()` / `revoke_deny()` — fully implemented |
| Delegation (grant a narrower slice, revocable, anti-redelegation) | A | `core.rbac.create_delegation()` / `create_delegation_to_service_account()` / `revoke_delegation()` — fully implemented |
| Service accounts / machine credentials | A | `core.identity.create_service_account()` + `core.api_keys` — fully implemented |
| Support access (time-boxed, audited cross-tenant access) | A | `core.rbac.create_support_access_request()` / approve / deny / revoke — fully implemented |
| User authentication (OIDC/ZITADEL), sessions | A | `core.identity` — fully implemented |
| Authorization policy evaluation (`can()`) | A | `core.rbac.authorization.can()` — fully implemented, the one chokepoint this product must always call, never reimplement |
| Product-specific permission *names* (e.g. `crm:contact.merge`) | C | SaaS-OS explicitly permits Product to define its own permission names evaluated through Core's existing mechanism (`saas-os` `docs/SECURITY.md` §3) — the names are product-specific, the evaluator is not |
| Custom-domain → tenant resolution | B (interim C) | Generic multi-tenant capability, but SaaS-OS has no domain-based tenant resolution at all — corrected 2026-09-19, post-Phase-2 implementation: this row previously claimed "SaaS-OS's ingress only resolves tenant by subdomain/header today," which direct inspection of the pinned `saas-os` commit disproved. The real chokepoint (`api.dependencies.get_tenant_context()`) resolves `tenant_id` from a FastAPI path parameter validated against session membership, never from `Host`/subdomain. This product's own `DomainResolutionMiddleware` (`docs/ROADMAP.md` Phase 2.4, shipped) resolves a custom domain to a `tenant_id` and stores it on `request.state` — it does not feed `get_tenant_context()`, and nothing consumes it yet (see `docs/WHITE-LABEL.md` §3 for the corrected data flow and the open consumption question). Propose upstream once a second product needs the same domain-resolution primitive |

## Billing, Entitlements, Subscriptions (Platform-Level)

| Capability | Category | Reasoning |
|---|---|---|
| Plans, subscriptions, entitlements, provider abstraction (Stripe) | A | `core.billing` — fully implemented. This is **this product's own SaaS revenue** (an agency paying for its subscription to this platform), not the agency's own customer invoicing |
| Usage metering, quota checks, hierarchy-aware aggregation | A | `core.usage` — fully implemented |
| Billing-owner resolution across agency/client hierarchy | A | `core.billing.resolve_billing_owner()` — fully implemented |
| Agency reselling plans to its own clients (sub-accounts on a metered/tiered plan the agency configures) | C | The *mechanism* (plans/subscriptions/entitlements) is A; the *reseller UI/workflow* (an agency defining its own resale pricing/plan tiers for its clients, on top of its own SaaS-OS subscription) is product-specific business logic — `product/billing/` |
| Trial periods, upgrades, downgrades, cancellation | A (mechanism) + C (product UI) | `core.billing.subscribe()` / `upgrade_subscription()` / `cancel_subscription()` already implement the lifecycle; this product's own onboarding/plan-selection UI is C |

## Audit, Secrets, Crypto, Idempotency

| Capability | Category | Reasoning |
|---|---|---|
| Append-only audit log | A | `core.audit_log` — fully implemented; every product-emitted audit event goes through this interface, never a second store |
| Secrets access | A | `infra.secrets` `SecretsProvider` — fully implemented; every credential this product needs (Twilio, WhatsApp, Stripe-for-tenant-payouts, etc.) is sourced through this, never `os.environ` directly |
| Application-level field encryption (for sensitive DB-stored values) | A | `core.crypto` (`EncryptionService`, `KeyProvider`, ADR-0019) — fully implemented; directly reusable for accounting/PII fields this product stores |
| Idempotency keys | A | `core.idempotency` — fully implemented; directly reusable for payment webhook processing in the accounting module and for any at-least-once job handler this product registers |
| Rate limiting | A | `infra.ratelimit` — fully implemented, applied uniformly by the platform ingress this product mounts into |

## Infrastructure

| Capability | Category | Reasoning |
|---|---|---|
| Database connection/session chokepoint, tenant scoping enforcement | A | `infra.db` — fully implemented |
| Background job execution, retry, dead-letter | A | `infra.jobs` — fully implemented (single-step jobs only; see `docs/ARCHITECTURE.md` §5 for multi-step) |
| Observability (structured logs, tracing, correlation context) | A | `infra.observability` — fully implemented |
| Health checks | A | `infra.health` — fully implemented |
| Object/file storage (attachments, call recordings, invoice PDFs, website assets, form uploads) | B (interim C/D) | No `infra/storage` module exists in SaaS-OS today — confirmed by direct inspection, no boto3/S3/MinIO dependency anywhere in `saas-os`. This is domain-agnostic plumbing (a tenant-namespaced object store, same isolation pattern `saas-os` `docs/MULTI-TENANCY.md` §4 already documents conceptually for "storage paths/buckets namespaced by tenant_id") — a strong future Category B candidate. Built in this product now as `product/foundation/storage.py`, a thin `Protocol` over an S3-compatible backend (D: the actual object-store provider), kept narrow enough to propose upstream later |
| Durable multi-step workflow engine | B (interim D) | See `docs/ARCHITECTURE.md` §5. SaaS-OS's own ADR-0007 explicitly reserves room for this later; this product needs it sooner (Automation, Phase 10) and evaluates/integrates an external engine (Temporal or similar) as its own dependency in the meantime |
| Generic internal event bus (module-to-module pub/sub) | B (interim C) | See `docs/ARCHITECTURE.md` §4. SaaS-OS documents event *ownership* rules but has no transport implementation; built product-side for now |

## AI Control Plane

| Capability | Category | Reasoning |
|---|---|---|
| Tool registry, invocation, sandboxing, RBAC-gated execution | A | `control_plane.orchestration` — fully implemented; this product registers its own tools against it, never builds a second agent runtime |
| Human approval gate workflow | A | `control_plane.approvals` — fully implemented |
| Tool Authorization / Data Authorization / Learning Authorization gates | A | `control_plane.data_authorization`, ADR-0013/0014 — fully implemented; every AI feature this product builds that touches an external LLM provider must pass through these, never call a provider directly |
| Self-Learning / Continuous Improvement (adaptive prompts, system-learning proposals, canary promotion) | A (available, not required) | Fully implemented (`saas-os` roadmap Phase 9) but not a Phase-1 dependency for this product — flagged as a later-phase opportunity (adaptive reply suggestions, etc.), not assumed in the initial roadmap |
| Product-specific tools (e.g. `summarize_conversation`, `qualify_lead`, `draft_reply`, `ai_receptionist_handle_call`) | C | Each is a bounded, product-specific capability registered by this product, per `saas-os` `docs/AI-CONTROL-PLANE.md` §3 — SaaS-OS owns the mechanism, this product owns every tool definition |
| External LLM/voice providers behind the tools above | D | Claude/OpenAI/etc. for text, an STT/TTS provider for voice — each wrapped by this product's own adapter, gated by the Data Authorization boundary (A) before any tenant data reaches them |

## CRM

| Capability | Category | Reasoning |
|---|---|---|
| Everything: contacts, companies, leads, opportunities, pipelines, stages, tasks, notes, activities, custom fields, tags, search/filter, import/export | C | Pure business-domain functionality — exactly what `saas-os` `docs/ARCHITECTURE.md` §1 defines as Product scope. No CRM concept exists anywhere in SaaS-OS, and none should |
| Tenant isolation of CRM data | A (mechanism) | Enforced by `infra.db`'s existing chokepoint once `crm.*` tables carry `tenant_id`, exactly like every other tenant-owned table — no new isolation mechanism needed |

## Marketing, Conversations, Websites

| Capability | Category | Reasoning |
|---|---|---|
| Campaigns, forms, landing pages, segmentation, marketing automation triggers | C | Product-specific. Must be clearly separated from SaaS-OS's own generic automation primitives (there are none beyond `infra.jobs`) — see `docs/ARCHITECTURE.md` §4–§5 |
| Unified conversation inbox (email/SMS/WhatsApp/chat threads, assignment, internal notes, templates) | C | Product-specific domain model. `core.notifications`/`core.email` (A) are the *outbound dispatch primitives* this reuses for sending, not a conversation model themselves |
| Outbound transactional email dispatch | A | `core.notifications` + `core.email` (SMTP provider) — fully implemented; reused as the sending mechanism inside `product/conversations/` and `product/marketing/`, not reimplemented |
| SMS/WhatsApp sending | D (+ C for the module) | No SMS/WhatsApp capability exists in SaaS-OS (`core.notifications`'s only implemented channel is email). Each is an external-provider adapter (Twilio, WhatsApp Business API, etc.) behind `product/integrations/`, invoked by `product/conversations/` and `product/marketing/` |
| Website/funnel builder, published pages | C | Product-specific; no equivalent concept anywhere near SaaS-OS's scope |

## Telephony

| Capability | Category | Reasoning |
|---|---|---|
| Call records, routing, recordings, phone-number management, human handoff | C | Product-specific domain model |
| Underlying telephony provider (carrier, SIP trunking, PSTN) | D | Provider-abstracted per `docs/INTEGRATIONS.md`; never assume one provider, per the brief's own requirement |
| AI voice agent logic (call handling, qualification) | C, built on A | Uses `control_plane` tool registry + this product's own telephony/conversation context; the voice/STT/TTS provider itself is D |

## Appointments

| Capability | Category | Reasoning |
|---|---|---|
| Calendars, availability, booking, rescheduling, cancellation, reminders, staff calendars | C | Product-specific |
| Reminder delivery | A | Reuses `core.notifications`/`core.email` (and SMS via D) as the send mechanism |
| Calendar provider sync (Google/Microsoft) | D | External integration, adapter-isolated |

## Automation / Workflow Builder

| Capability | Category | Reasoning |
|---|---|---|
| Trigger/condition/action definitions specific to this product's domain (pipeline stage changed, form submitted, invoice overdue, ...) | C | Entirely product-specific; SaaS-OS has no workflow-trigger concept |
| Single-step action execution (send email, create task, ...) | A (substrate) + C (actions) | Runs on `infra.jobs` (A); each action's business logic is product-owned (C) |
| Multi-step/branching/delayed workflow durability | B (interim D) | See `docs/ARCHITECTURE.md` §5 |
| Generic trigger/condition/action *framework shape* (if it proves reusable beyond marketing automation) | B (future candidate) | Not proposed upstream now — no second product exists yet to prove the abstraction is right; SaaS-OS's own doctrine (evidence before infrastructure) applies here to this product's own architecture, not only to SaaS-OS's |

## Reputation Management

| Capability | Category | Reasoning |
|---|---|---|
| Review requests, tracking, responses, automation hooks | C | Product-specific |
| Review platform integration (Google Business Profile, Facebook, etc.) | D | External integration adapters |

## Agency / Client Management

See `docs/ARCHITECTURE.md` §3 for the full mapping. Summary: the
authorization/tenancy mechanics are **A** (already built and validated by
`saas-os`'s own reference-consumer scenarios); the agency-facing UI,
client-onboarding workflow, and product-specific default provisioning
(starter pipeline, default automation templates for a new client) are **C**.

## White-Label

| Capability | Category | Reasoning |
|---|---|---|
| Per-tenant branding (logo, colors, custom domain, email branding, login branding) | C (interim), borderline B | Generic enough that other white-label SaaS products would want it, but SaaS-OS has no branding/theming concept today and no second product to validate the abstraction against yet. Built product-side, designed as a `BrandingProvider` interface (mirroring SaaS-OS's own Stripe/SMTP Provider pattern) so it can be donated upstream later. See `docs/WHITE-LABEL.md` |
| Custom domain routing | B (interim C) | Same reasoning as the tenancy-resolution row above |

## Templates / Snapshots

| Capability | Category | Reasoning |
|---|---|---|
| Cloning a set of product configuration (workflows, pipelines, forms, campaigns, ...) across tenants | C | Product-specific — the *content* being cloned (pipelines, forms, campaigns) is entirely product-owned data. The cloning mechanism reuses `infra.db`'s ordinary tenant-scoped write path; no new SaaS-OS primitive is implied |

## Reporting

| Capability | Category | Reasoning |
|---|---|---|
| Operational analytics (leads, conversion, pipeline, appointments, campaigns, communication) | C | Product-specific, reads this product's own module data |
| Accounting reports (P&L, balance sheet, VAT summary, AR/AP) | C | See `docs/ACCOUNTING-SCOPE.md` — entirely product-owned, distinct data and distinct concern from operational analytics; never conflated in the same report module |
| Usage/entitlement reporting (platform subscription usage) | A | `core.usage`/`core.billing` already expose this; this product's reporting UI is a thin presentation layer over it |

## Mini Accounting

See `docs/ACCOUNTING-SCOPE.md` for the full breakdown. Summary categories:

| Capability | Category | Reasoning |
|---|---|---|
| Chart of accounts, journal entries, ledger, periods, invoices (tenant's own customer invoices), payments, expenses, bank transaction import/reconciliation | C | Entirely product-specific bookkeeping domain. Must never be confused with `core.billing`'s Invoice/Subscription model, which is this platform's own SaaS revenue, not the tenant's own customer invoicing — see the explicit warning in `docs/ACCOUNTING-SCOPE.md` §"The One Mistake to Avoid" |
| Audit trail for financial records | A (mechanism) | `core.audit_log` is reused as the audit interface; the immutability guarantee on journal entries themselves (no UPDATE/DELETE once posted) is this product's own data-model discipline, following the same pattern `core.audit_log` itself uses, not a SaaS-OS primitive this product calls |
| Idempotent payment-webhook processing | A | `core.idempotency` — fully implemented, directly reusable |
| Field-level encryption for sensitive financial data | A | `core.crypto` — fully implemented, directly reusable |
| Bank data aggregation provider | D | PSD2 AIS provider (e.g. a Netherlands-focused aggregator), adapter-isolated, never assumed at initial launch |
| VAT/tax calculation and reporting rules | C | Jurisdiction-specific business logic; see Dutch-market considerations in `docs/ACCOUNTING-SCOPE.md` |

## Prospecting & Lead Intelligence (Phase 19–20, design-only at this revision)

| Capability | Category | Reasoning |
|---|---|---|
| Prospecting domain model (`Prospect`, `ProspectCandidate`, `ProspectSearch`, `ProspectSource`, `ProspectSignal`, `ProspectEnrichment`, `ProspectAudit`, `ProspectQualification`, `ProspectAssignment`) | C | Product-specific, country-agnostic domain model — no equivalent concept exists in SaaS-OS. `docs/ROADMAP.md` Phase 19.2 |
| Discovery / enrichment / registry / audit providers (external business-data, directory, registry, and audit-intelligence sources) | D | External providers, adapter-isolated behind `DiscoveryProvider`/`EnrichmentProvider`/`RegistryProvider`/`AuditProvider` Protocols, per `docs/INTEGRATIONS.md`'s existing pattern — no vendor is fixed by this roadmap update. `docs/ROADMAP.md` Phase 19.1, 19.3 |
| Business identity resolution / deduplication across sources | C | Product-specific matching logic over CRM (C) and provider (D) data; not a generic SaaS-OS capability, and not proposed as one — no second product yet demonstrates the need. `docs/ROADMAP.md` Phase 19.5 |
| External-data provenance/licensing metadata (source, `observed_at`, confidence, license classification) | C | Product-specific schema design, reusing `core.crypto` (A) for any sensitive field, exactly as Accounting already does. `docs/ROADMAP.md` Phase 19.6 |
| Business/marketing audit capability (website, SEO, listings, reviews, technical signals) | C | Product-specific, reusable across prospects and existing CRM entities; no SaaS-OS equivalent. `docs/ROADMAP.md` Phase 19.8 |
| CRM handoff (external candidate → Prospect → Company/Contact → Opportunity → Pipeline) | A (mechanism, reused) + C (handoff logic) | Reuses Phase 4's existing `crm.*` entities, services, and `core.rbac.can()` authorization (per ADR-0002's `get_current_actor` pattern) unchanged — **no second CRM, no duplicate Company/Contact/Opportunity model**. `docs/ROADMAP.md` Phase 19.9 |
| Prospecting domain events (`prospect.discovered`, `.enriched`, `.qualified`, `.audit_completed`, `.converted`) | B (interim C) | Rides the existing product event dispatcher (`docs/ARCHITECTURE.md` §4, already Category B interim) — no new event mechanism. `docs/ROADMAP.md` Phase 19.10 |
| Prospecting automation triggers/actions (scheduled search, recurring discovery, enrichment, qualification, audit, CRM handoff, assignment) | C, built on A+B | Consumes Phase 10's existing trigger/condition/action framework (A substrate via `infra.jobs`, B-interim durable engine once built) — **no second automation engine**. `docs/ROADMAP.md` Phase 20.1 |
| Prospecting budget/quota/rate controls | A (mechanism, reused) | Maps onto `core.usage`/`core.billing` (already A) and `core.idempotency` (already A) for duplicate-request prevention — **no second usage/entitlement/billing system**. `docs/ROADMAP.md` Phase 20.2 |
| AI-assisted prospecting agents (research assistance, qualification interpretation) | C, built on A | `control_plane` tool registrations at autonomy tier 0/1 only, per the existing Phase 9.1 pattern; gated by Data Authorization (ADR-0013) before any content reaches an external LLM. `docs/ROADMAP.md` Phase 20.3 |
| Prospecting provider credentials | A (mechanism, reused) | `infra.secrets`'s `SecretsProvider`, per `docs/INTEGRATIONS.md`'s existing credential-handling rule — never stored in a CRM record, never a second secrets mechanism |

**Architecture boundary (explicit)**: `Product Prospecting → SaaS Core →
Infrastructure`, and `AI Prospecting/Agents → Product Prospecting → SaaS
Core → Infrastructure`. Never the reverse — SaaS Core never depends on
Product Prospecting. No prospecting-specific code belongs in `saas-os`, per
`docs/ARCHITECTURE.md` §1's binding layer rule, applied here exactly as it
already applies to every other module in this table. See ADR-0004.

## Integrations (Cross-Cutting)

Every external provider this product touches — email is the one exception
already covered by SaaS-OS's `core.email` — is Category D, wrapped by an
adapter in `product/integrations/`, following the exact Protocol+Fake+adapter
pattern SaaS-OS already uses internally for Stripe (`core/billing/provider.py`
+ `stripe_provider.py`) and SMTP (`core/email/provider.py` +
`smtp_provider.py`). See `docs/INTEGRATIONS.md` for the full list and the
adapter contract.

## Frontend

| Capability | Category | Reasoning |
|---|---|---|
| Entire product UI (dashboard, CRM screens, pipeline board, automation builder, accounting screens, agency admin console, client-facing portal) | C | No product UI exists in SaaS-OS beyond a placeholder page; entirely product-owned |
| Auth/session UI flow (login redirecting to ZITADEL OIDC) | A (mechanism) | `core.identity` owns the OIDC relying-party logic this product's frontend calls into; the actual screens are product-owned |
