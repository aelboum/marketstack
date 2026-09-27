# ADR 0016: Branded login UX vs. provider-agnosticism — keep the hosted OIDC redirect

## Status

Accepted (investigation-only; no implementation authorized by this ADR).
**Partially superseded by `docs/ADR/0017-product-owned-zitadel-login-service.md`:**
a follow-up compatibility audit found a revised, server-side-credential
shape of Option B (below) that avoids this ADR's stated Option B costs;
ADR-0017 records that decision. Option A, Option C, and the general
Security requirements section below remain in force as background and are
not superseded.

## Context

The product requirement under review: a user visiting
`http://localhost:8080/login` should see a Marketstack-branded page, never
`http://zitadel.localhost:8081`, and should land on
`http://localhost:8080/dashboard` once authenticated. ZITADEL remains the
identity authority throughout.

The current flow (`api/auth/routes.py`, the installed `saas-os` dependency)
is a standards-based OIDC Authorization Code + PKCE exchange:
`/auth/login` redirects the browser to ZITADEL's own hosted login page;
`/auth/callback` performs the server-side token exchange, validates the ID
token, and issues Marketstack's own session cookie. This is why the user
currently sees `zitadel.localhost:8081` — the Authorization Code flow
requires the user to authenticate directly with the identity provider's
own UI, on the provider's own origin, precisely so that no Marketstack
code (frontend or backend) ever receives the password.

Two SaaS-OS decisions bound this repository's options, and this ADR does
not revisit either:

- **ADR-0005** (`saas-os`, "identity build vs. buy") — `core/identity/oidc.py`'s
  own module docstring states the property directly: "no ZITADEL-specific
  behavior is hardcoded here... a swap to a different OIDC-compliant IdP
  must be a configuration change, not a platform-wide rewrite." Nothing in
  the current login flow depends on a ZITADEL-specific API.
- **ADR-0024** (`saas-os`, single-origin application runtime) — unifies
  Marketstack's own frontend and backend onto one browser-visible origin
  (`PUBLIC_APP_ORIGIN`, `http://localhost:8080` locally). It does not, and
  was never intended to, extend that origin to the identity provider
  itself — `infra/edge/__init__.py`'s own boundary section is explicit that
  SaaS-OS owns origin composition for the product's own two servers, not a
  third-party IdP.

Both live in the `saas-os` dependency and are not modified by this ADR.

An investigated alternative exists and was verified against the installed
local ZITADEL v4.19.0: its Session API v2
(`zitadel.session.v2.SessionService`, `zitadel.user.v2.UserService`) is
live and routed (`POST` to either returns `401`, not `404`, distinguishing
"exists, needs auth" from "no such route"). The flow would be:
Marketstack's own frontend renders a branded form; the browser calls
ZITADEL's Session API directly (never through Marketstack's backend) to
authenticate; on success ZITADEL sets its own session cookie; the browser
is then sent through the *existing, unchanged* `/auth/login` →
Authorization Code + PKCE → `/auth/callback` path, which now completes as
a silent SSO redirect (a valid ZITADEL session already exists, so no
hosted UI is ever painted) rather than a rendered login screen. A naive
"just iframe the hosted page" idea was also checked and is not viable at
all: the hosted login page serves `X-Frame-Options: DENY` and
`frame-ancestors 'none'` — a deliberate ZITADEL anti-clickjacking
control, verified live against this instance.

## Decision

**Keep the existing hosted OIDC redirect (Option A). Do not build the
ZITADEL Session API v2 branded login (Option B) as a default
implementation.** Option C (an authentication broker/proxy) is rejected
outright, not merely deprioritized.

### Option A — hosted OIDC redirect (current, unchanged)

Advantages: provider-agnostic (ADR-0005's own property, currently true and
left true); smallest attack surface — Marketstack never runs any
authentication-adjacent code, so there is nothing new to secure; ZITADEL's
complete, already-correct MFA UI (OTP, WebAuthn, whatever factors a tenant
enrolls) is used as-is, with no reimplementation risk; no new CORS trust
relationship between `localhost:8080` and ZITADEL's API.

Disadvantage: the user is shown the identity provider's own origin/UI for
the duration of the login step.

### Option B — Marketstack-branded login via ZITADEL Session API v2

Advantages: Marketstack owns the visible login experience; no ZITADEL
hosted screen is shown; the password still travels browser → ZITADEL
only, never through Marketstack's backend.

Disadvantages, all real and all accepted as costs if this option is ever
chosen later: (1) ZITADEL-specific frontend integration — a new,
non-generic client against `zitadel.session.v2`/`zitadel.user.v2`, the
literal opposite of ADR-0005's "no ZITADEL-specific behavior" property;
(2) a deliberate, explicit exception to ADR-0005 — not a violation
smuggled in silently, a recorded one, and only for the login *presentation*
layer (`/auth/callback` and everything after it stays exactly as generic
as today); (3) ZITADEL instance CORS must be opened to the Marketstack
origin, a new trust relationship that does not exist today; (4) every MFA
factor ZITADEL's hosted UI supports must be reimplemented in Marketstack's
own UI as a state machine, or enrolled users regress; (5) logout must gain
a second, ZITADEL-aware call in addition to the existing
`revoke_session()`/cookie-clear, or a ZITADEL-side session can outlive the
user's intent to sign out; (6) ongoing maintenance coupling to ZITADEL
Session API v2's own evolution, a dependency this product does not
currently have; (7) new security-sensitive frontend code (credential
collection, multi-step session negotiation) where today there is none —
Marketstack's frontend currently contains zero authentication logic
(`frontend/app/page.tsx`'s own comment: "this frontend still implements no
auth logic of its own").

### Option C — authentication broker/proxy

Rejected outright. A broker sitting between the browser and ZITADEL must
do one of two things: redirect the browser to ZITADEL to actually
authenticate, which reproduces the exact visible-origin-change this ADR
is about and solves nothing; or collect/forward the password itself,
which is precisely the pattern the security requirements below forbid.
Either way it adds a new stateful service and a new trust boundary for a
result that is strictly worse than or redundant with Option A/B. Not
attractive under any framing.

## Security requirements (binding on any future implementation)

Whether this product ever revisits Option B or not, the following are
non-negotiable and this ADR records them so a later implementer cannot
relitigate them piecemeal:

- The Marketstack backend never receives the user's ZITADEL password, in
  any form, at any layer.
- Marketstack never proxies the password, server-side, under any
  circumstance.
- No Resource Owner Password Credentials grant, ever — not as a shortcut,
  not as a fallback.
- No password storage, anywhere in Marketstack.
- No password logging, anywhere in Marketstack (matches
  `core/identity/oidc.py`'s existing discipline of never logging a raw
  token either).
- No iframing of ZITADEL's hosted login — moot regardless, since ZITADEL
  itself refuses it (`X-Frame-Options: DENY`, `frame-ancestors 'none'`,
  verified above).
- Authorization Code + PKCE remains the final, sole application
  authentication mechanism — a Session-API-based login (if ever built)
  is a *presentation* change in front of that flow, never a replacement
  for it.
- Existing ID-token validation (`core/identity/oidc.py::validate_id_token`
  — asymmetric-algorithm-only, issuer/audience/nonce checked) is
  unchanged.
- The existing Marketstack session mechanism (`issue_session()`, the
  HttpOnly cookie) remains the sole application session boundary — no
  second, parallel session concept.
- MFA must never be silently weakened — any custom login UI must offer
  every factor ZITADEL's hosted UI offers, not a subset chosen for
  implementation convenience.
- If a custom flow is ever adopted, logout must invalidate both the
  Marketstack application session and the relevant ZITADEL-side
  authentication state — today's logout (Marketstack-only) is
  insufficient the moment a ZITADEL session is created outside the
  Authorization Code flow itself.

## Rejected Alternative

Option B was investigated in full (see Context) and is rejected as the
default path specifically because its cost is a real, ongoing
architectural one (a permanent ADR-0005 exception plus new maintenance
surface) purchased for a cosmetic benefit (removing a login-time domain
flash that is a well-understood, common pattern across "sign in with
your identity provider" products generally and is not, by itself, a
security or functional defect). It is recorded here as a bounded,
revisitable option rather than closed off entirely: if a future product
decision makes the literal branded-URL requirement non-negotiable, this
ADR's Option B section and Security requirements section are the starting
point for that implementation — not a fresh design.

## Consequences

- No code changes result from this ADR. `/auth/login`, `/auth/callback`,
  `frontend/app/page.tsx`, and every `saas-os` module are unchanged.
- A future implementer choosing to revisit Option B must update this ADR's
  Status (or file a superseding ADR) rather than build it as an
  undocumented deviation from ADR-0005.
- If the real driver behind this request is brand perception rather than
  the literal URL-bar requirement, the lowest-risk alternative — ZITADEL's
  own Private Labeling/custom branding on the existing hosted page, and
  optionally a friendlier ZITADEL hostname — achieves most of the
  perceived benefit with none of Option B's costs, and is not blocked by
  this ADR.

## Related ADRs

- SaaS-OS `docs/ADR/0005-identity-build-vs-buy.md` — the provider-agnostic
  identity property this ADR declines to break by default.
- SaaS-OS `docs/ADR/0024-single-origin-application-runtime.md` — the
  single-origin contract this ADR confirms does not, and was never meant
  to, extend to the identity provider.
- `docs/ADR/0001-naming-and-identifier-neutrality.md` — this product's own
  neutrality/branding conventions, relevant if the Private Labeling
  fallback above is pursued instead.
