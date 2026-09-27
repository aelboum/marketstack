# ADR 0017: Product-owned custom ZITADEL Login UI/server via the Session API

## Status

Accepted. Supersedes the Option B rejection in
`docs/ADR/0016-branded-login-ux-vs-provider-agnosticism.md` (architecture
decision only; implementation not authorized by this ADR).

## Context

ADR-0016 investigated branded login and rejected Option B (a Marketstack
frontend calling ZITADEL's Session API v2 directly from the browser) as the
default path, primarily because that shape required the browser to hold a
CORS trust relationship with ZITADEL and because it conflated "who presents
the login UI" with "who owns platform session/tenant/RBAC concerns."

A further compatibility audit has since established a materially different
shape for Option B: a **product-owned custom Login UI/server**, sitting
server-side between the browser and ZITADEL, using ZITADEL's per-application
`loginVersion.loginV2.baseUri` integration point and the ZITADEL Session API
from the server, not the browser. This audit verified:

- SaaS-OS requires no code changes under this shape.
- SaaS-OS remains an OIDC relying party and does not need to know which
  Login UI authenticated the user.
- The existing SaaS-OS PKCE/state/nonce/callback/session architecture is
  unaffected.
- The existing Marketstack OIDC issuer and OIDC application identity can
  remain unchanged.
- ZITADEL's `loginVersion.loginV2.baseUri` is the documented, supported
  integration point for a custom Login UI, distinct from the browser-side
  Session API approach ADR-0016 evaluated.
- The privileged ZITADEL credential needed to call the Session API
  (`session.write`, `session.link`, `session.delete`) can be held entirely
  server-side, in the new Login service, and never reaches browser
  JavaScript.

This is a narrower, better-bounded version of what ADR-0016 called Option B.
It does not reopen ADR-0016's rejection of Option C (broker/proxy), and it
does not revisit ADR-0005 or ADR-0024 (both remain SaaS-OS decisions, both
unmodified).

## Decision

Marketstack will use a **product-owned custom ZITADEL Login UI/server** for
branded authentication, superseding ADR-0016's rejection of Option B for
this revised shape.

The custom Login service will:

- receive the ZITADEL Login V2 authorization request;
- retrieve the authorization request from ZITADEL;
- present the Marketstack-branded authentication UI;
- perform authentication through the ZITADEL Session API, server-side;
- enforce the required authentication factors before proceeding (see
  Security requirements — ZITADEL's `CreateCallback` does not by itself
  guarantee configured MFA policy was satisfied);
- complete the OIDC authorization request through ZITADEL;
- redirect the browser to the existing, unchanged SaaS-OS OIDC callback.

SaaS-OS remains responsible for, unchanged:

- OIDC relying-party behavior;
- authorization-code exchange, PKCE, state, nonce;
- ID-token validation;
- SaaS-OS sessions;
- tenant resolution;
- RBAC and application authorization.

SaaS-OS is not changed to own credential authentication, and this decision
is Marketstack-specific — no SaaS-OS concept, ADR, or code is touched.

## Architecture boundary

```text
                    ZITADEL
                       ▲
                       │
                Session API
                       │
                       │ privileged server-side
                       │ credential
                       │
        ┌──────────────┴──────────────┐
        │ Marketstack Custom Login    │
        │ UI + server                 │
        │                             │
        │ Product-owned authentication│
        │ orchestration               │
        └──────────────┬──────────────┘
                       │
                       │ OIDC callback
                       ▼
              ┌──────────────────┐
              │     SaaS-OS      │
              │                  │
              │ OIDC RP          │
              │ session          │
              │ tenant           │
              │ RBAC             │
              └──────────────────┘
```

`SaaS-OS does NOT call the ZITADEL Session API for credential
authentication.` The product-owned Login service does, exclusively.

Full flow, showing that this only changes authentication *presentation and
orchestration* inside ZITADEL's Login UI boundary, not the SaaS-OS
callback/session architecture:

```text
Browser
  → SaaS-OS /auth/login
  → ZITADEL authorization endpoint
  → Custom product-owned Login UI
  → ZITADEL Session API
  → ZITADEL authorization completion
  → SaaS-OS /auth/callback
  → SaaS-OS session
  → tenant resolution
  → RBAC
```

## Why this decision

1. SaaS-OS remains a reusable, provider-agnostic OIDC relying party
   (ADR-0005's property in the SaaS-OS repo is preserved).
2. Product-specific branding stays outside SaaS-OS.
3. Credential-handling capability does not become part of SaaS-OS.
4. Marketstack can own its login UX independently of other SaaS-OS
   consumers.
5. Other SaaS-OS consumers can continue using the normal ZITADEL hosted
   login UI unaffected.
6. The custom Login service can be removed later without any SaaS-OS
   change — it is additive at the ZITADEL layer, not a fork of the OIDC
   relying-party path.
7. Existing SaaS-OS authentication/session boundaries (PKCE, state, nonce,
   ID-token validation, `issue_session()`) remain exactly as they are.
8. The privileged ZITADEL Session API credential stays server-side, never
   in browser JavaScript — the specific defect that made ADR-0016's
   originally-evaluated Option B (browser-side Session API calls) require
   a new browser↔ZITADEL CORS trust relationship is avoided by construction.

This is the selected architecture for Marketstack. It is not claimed to be
the only valid architecture for branded login in general.

## Explicit non-goals

This decision does **not**:

- modify SaaS-OS authentication;
- move passwords into SaaS-OS;
- make SaaS-OS a credential authentication provider;
- make SaaS-OS responsible for MFA;
- replace SaaS-OS's OIDC relying-party role;
- change the SaaS-OS issuer/callback architecture;
- require a fresh-profile same-origin ZITADEL migration;
- require changing the existing Marketstack OIDC application identity;
- implement the custom Login service;
- implement Caddy routing;
- create credentials;
- implement password reset;
- implement WebAuthn/passkeys;
- implement MFA;
- change ZITADEL configuration.

All of the above are implementation concerns for a later phase.

## Security requirements (binding on the eventual implementation)

### Privileged credential

- The Login service must use a server-side ZITADEL identity capable of
  `session.write` / `session.link` / `session.delete`.
- This credential must never reach browser JavaScript, must never be
  stored in Git, and must never be placed in frontend configuration.
- Prefer the existing ZITADEL system-user / private-key JWT mechanism
  (deploy-time generated) over a persistent PAT.
- The credential must be mounted only into the Login service, and must
  not be reused as the ZITADEL bootstrap/admin credential.
- This ADR does not document a concrete secret value.

### Authentication-factor enforcement

`session.write` combined with `session.link` is an impersonation-capable
combination, and ZITADEL's `CreateCallback` does not by itself guarantee
that the required authentication factors were satisfied. The custom Login
service — not ZITADEL automatically — is responsible for correctly
implementing the required authentication ceremony (password, MFA,
WebAuthn/passkey, external IdP, as applicable) and for verifying the
required factors are actually satisfied before finalizing the OIDC
authorization request. This ADR does not design that ceremony's
implementation; it records the requirement so a later implementer cannot
skip it.

### Login-ceremony cookie isolation

The custom Login service's own authentication-ceremony cookies must not
reach SaaS-OS product API routes (`/auth/*`, `/v1/*`). The implementation
must provide an edge isolation/stripping boundary enforcing this. Not
implemented by this ADR — recorded as a mandatory implementation
requirement.

### SaaS-OS boundary

No SaaS-OS changes are expected as a result of this ADR. Any future
proposal to modify SaaS-OS itself must undergo a separate architecture
review in the SaaS-OS repository and must remain product-agnostic.

## Consequences

- No code changes result from this ADR. The custom Login service, its
  ZITADEL Session API integration, its privileged credential, its
  authentication-factor enforcement, its Login V2 application
  configuration, its edge routing, and its cookie isolation boundary are
  all future implementation work, not authorized here.
- `docs/ADR/0016-branded-login-ux-vs-provider-agnosticism.md` remains the
  historical record of the original investigation and the reasons the
  browser-side Session API shape was rejected as a default; its Option A
  (hosted redirect), Option C (broker, rejected outright) analysis, and
  general security requirements section remain valid background. Its
  Option B rejection is superseded by this ADR for the revised,
  server-side-credential shape described here.
- A future implementer must not treat this ADR as authorization to build
  the Login service without further review of its concrete design
  (authentication ceremony, MFA parity, logout/provider-session handling).

## Related ADRs

- `docs/ADR/0016-branded-login-ux-vs-provider-agnosticism.md` — superseded
  in part (Option B rejection) by this ADR; its Option A/C analysis and
  general security requirements remain in force as background.
- SaaS-OS `docs/ADR/0005-identity-build-vs-buy.md` — the provider-agnostic
  identity property this ADR preserves (SaaS-OS still never calls the
  ZITADEL Session API).
- SaaS-OS `docs/ADR/0024-single-origin-application-runtime.md` — unaffected;
  the custom Login service lives at the ZITADEL Login V2 integration point,
  not inside SaaS-OS's single-origin application runtime.
- `docs/ADR/0001-naming-and-identifier-neutrality.md` — this product's own
  naming/branding conventions apply to the Login service's UI.
