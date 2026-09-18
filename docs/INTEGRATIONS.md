# Integration Strategy

Status: PROPOSED. Every capability below is Category D in
`docs/RESPONSIBILITY-MATRIX.md`, wrapped by an adapter this product owns in
`product/integrations/`.

## The Pattern (Reused, Not Invented)

SaaS-OS already establishes the pattern this product follows for every
external provider — visible directly in `core/billing/provider.py` +
`stripe_provider.py` (a `BillingProvider` Protocol, one concrete adapter) and
`core/email/provider.py` + `smtp_provider.py` (an `EmailProvider` Protocol,
one concrete adapter):

```
product/integrations/<capability>/
    provider.py     # Protocol — the capability's abstract interface
    <name>_provider.py   # one concrete adapter per provider
    errors.py       # typed errors, provider-agnostic
```

Module code (`product/conversations/`, `product/telephony/`, ...) depends on
the Protocol only, never on a specific provider's SDK types leaking past the
adapter boundary — exactly the discipline `saas-os`
`docs/ADR/0008-billing-provider.md` states for `core.billing`: "No Core or
Product code depends on Stripe-specific types — only the adapter does,"
applied here one level down, to this product's own external providers.

A substitution test (a fake/mock adapter satisfying the same Protocol) is
part of every integration's test suite, proving the abstraction isn't leaky
— the same acceptance criterion `saas-os` roadmap Phase 5.1 already applied
to `core.billing`.

## Integration Categories and Providers (Never Assume One)

| Category | Capability | Provider abstraction — never hardcode one |
|---|---|---|
| Email | Transactional/marketing email sending | Already A via `core.email` (SMTP provider); a marketing-specific provider (e.g. one with better deliverability/analytics for bulk send) may be added as a second adapter behind the same Protocol if `core.email`'s SMTP-only shape proves insufficient for bulk campaign volume |
| SMS | Outbound/inbound SMS | Twilio, MessageBird, Vonage, or similar — `SmsProvider` Protocol |
| WhatsApp | WhatsApp Business API messaging | Meta's own Cloud API, or a BSP (Business Solution Provider) — `WhatsAppProvider` Protocol |
| Telephony | Voice calls, recording, routing | A SIP/carrier provider (e.g. Twilio Voice, Vonage, or a FreeSWITCH-based deployment) — `TelephonyProvider` Protocol. Provider-abstracted per the brief's explicit requirement ("do not assume one telephony provider") |
| AI / LLM | Text generation, summarization, reply drafting | Already routed through `control_plane`'s Data Authorization boundary (A); the underlying model provider (Claude, others) is swappable behind that boundary, never called directly by product code |
| AI / Voice | STT/TTS for voice agents | A dedicated STT/TTS provider, adapter-isolated; kept separate from the text-LLM adapter above since voice providers and text-model providers are typically different vendors |
| Payment (tenant's own, for accounting) | Payment collection on the tenant's own invoices (distinct from this platform's own Stripe billing relationship, which is `core.billing`, Category A) | A payment-collection provider the tenant configures for their own customers — adapter-isolated, never conflated with `core.billing`'s Stripe integration (see `docs/ACCOUNTING-SCOPE.md` §"The One Mistake to Avoid") |
| Banking | Bank transaction aggregation (Phase 2 of `docs/ACCOUNTING-SCOPE.md`'s bank-integration phasing) | A PSD2 AIS provider covering Dutch banks — adapter-isolated, not built at launch |
| Calendar | Google Calendar / Microsoft 365 sync | `CalendarProvider` Protocol, one adapter per provider |
| Domains/DNS | Custom domain provisioning (`docs/WHITE-LABEL.md` §3) | Provider covering DNS/ACME automation for the proxy layer |
| Analytics | Website/funnel/campaign tracking | A pixel/analytics provider, or a self-hosted option — deferred to the relevant phase, not decided here |
| Reputation | Review platform integration | Google Business Profile, Facebook, others — adapter-isolated |

## Credential Handling

Every integration's credentials (API keys, OAuth tokens, webhook signing
secrets) flow through `infra.secrets`'s `SecretsProvider` — never read from
`os.environ` directly inside an adapter, never a second secrets mechanism.
Where an integration is AI-Control-Plane-invoked (e.g. a tool that sends an
SMS), the tool declares its required secret name per `saas-os`
`docs/AI-CONTROL-PLANE.md` §3 ("Tool Secrets Access") — the tool receives the
resolved value in its execution context only, never in the invoking agent's
conversational context.

A tenant-supplied integration credential (e.g. a client's own payment
provider API key, or their own Twilio account) is itself sensitive tenant
data — stored through `core.crypto`'s field-level encryption (Category A),
never in plaintext, and never readable by another tenant regardless of
hierarchy position (an agency does not automatically see a client's own
integration secrets merely by virtue of `SUBTREE` role scope — this needs an
explicit product-level decision at the relevant phase about whether/how an
agency can view vs. only rotate a client's credential).

## Webhook Security (Inbound, From Providers)

Every inbound provider webhook (payment confirmation, SMS delivery status,
call completion, etc.) is signature-verified before being trusted, following
the same discipline `core.webhooks`'s own outbound-delivery signing already
demonstrates (`compute_signature`/`verify_webhook_signature` in
`saas-os`). An unverified or replayed webhook is rejected, not processed —
idempotency (`core.idempotency`, Category A) guards against a legitimately
retried webhook being double-processed.

## What This Document Does Not Decide

Specific vendor selection (which SMS provider, which telephony provider) is
a Phase-level decision made when that phase actually starts, weighing cost,
Dutch-market coverage, and API quality at that time — not fixed
prematurely here. This document fixes the *pattern* (Protocol + adapter,
never a hardcoded single-vendor assumption), not the vendor.
