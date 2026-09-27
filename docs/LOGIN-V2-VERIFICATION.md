# Login V2 End-to-End Verification

Status: **VERIFICATION RECORD**, not an architecture decision and not a
production-readiness approval. `docs/ADR/0017-product-owned-zitadel-login
-service.md` remains the accepted architecture decision this document
verifies against — this file does not supersede or modify it. Where this
document and ADR-0017 appear to disagree, ADR-0017's decision stands;
this document only records what was actually observed against a real
local ZITADEL v4.19.0 instance and a real, running local docker-compose
stack, on 2026-09-27, at security checkpoint `75eadf23f31dc524c775c462ed8542e558e86ac0`.

## Login V2 verification status: READY WITH DOCUMENTED LIMITATIONS

This is a **verification status**, describing what was and was not
observed working in the local development environment. It is explicitly
**not** a statement that Login V2 authentication is verified end-to-end,
and it is explicitly **not** a production-readiness sign-off. See
"Remaining limitations" and "Production/custom-domain verification"
below.

## Architecture verified

The accepted architecture (ADR-0017):

```text
Browser
  ↓
ZITADEL OAuth/OIDC authorization
  ↓
ZITADEL Login V2
  ↓
Marketstack Login Service
  ↓
ZITADEL Session API
  ↓
ZITADEL OIDC callback
  ↓
SaaS-OS /auth/callback
  ↓
SaaS-OS session
  ↓
tenant resolution / RBAC
```

**Only the first portion of this chain was live/local verified**: a real
authorization request issued by SaaS-OS's own `/auth/login` was followed
through ZITADEL's real authorization endpoint to a real redirect landing
on the Marketstack Login Service's branded page, and a real (deliberately
invalid) credential submission was driven through the Login Service into
ZITADEL's real Session API (`CreateSession`), observed in the ZITADEL
container's own logs.

**The remainder of the chain — a *successful* authentication continuing
through `CreateCallback` into SaaS-OS's `/auth/callback`, a SaaS-OS
session, tenant resolution, and RBAC — was NOT completed or observed.**
No suitable existing local test account with known credentials was
available, and creating one was outside the scope of the verification
that produced this record. Do not read the verified portion above as
implying the full chain was exercised.

## Verification matrix

| Area | Status | Evidence / limitation |
| --- | --- | --- |
| Login V2 → Login Service | VERIFIED | Real local ZITADEL authorization redirected to `http://localhost:8080/login-svc/login?authRequest=...` |
| Branded Login UI | VERIFIED | Login Service page served successfully (200, title "Sign in - Product", form posts to `/login-svc/login/password`) |
| Login Service → Session API | VERIFIED | Real `CreateSession` call observed in the ZITADEL container's own logs (`service=zitadel.session.v2.SessionService`) |
| SaaS-OS OIDC RP boundary | VERIFIED | Real `/auth/login` produced a fresh PKCE/state/nonce authorization redirect to ZITADEL |
| OIDC callback | NOT VERIFIED | Requires a successful authentication, which did not occur |
| Authenticated `/auth/me` | NOT VERIFIED | Requires a successful authentication; only the unauthenticated (401) path was observed |
| Tenant resolution | NOT VERIFIED | Requires an authenticated session |
| Tenant/RBAC authorization | NOT VERIFIED | Requires an authenticated session |
| Cookie isolation | VERIFIED | Live cookie-jar verification: the Login Service's ceremony cookie (`Path=/login-svc`) was sent to `/login-svc/healthz` and absent from both `/auth/me` and `/v1/...` on the same origin |
| Invalid password | VERIFIED | Live failure path: generic "Invalid email or password." message, no `Set-Cookie`, no redirect; ZITADEL's own logs show `CreateSession ... code=not_found` and zero `CreateCallback` calls |
| Provider/service failure | VERIFIED | Covered by the Login Service security test suite, executed successfully during the verification (not exercised against the live ZITADEL container, to avoid disrupting it) |
| TOTP/MFA | BLOCKED | No existing local MFA-enrolled test account available |
| WebAuthn/passkey | NOT EXECUTED | No usable local WebAuthn credential available; delegation-to-ZITADEL architecture confirmed statically and via the executed test suite instead |
| Logout | PARTIAL | Static/test-suite evidence only (already checkpointed F-05 work); no authenticated live session existed to actually log out of |
| Production Login V2 | NOT VERIFIED | No production environment or credentials exist in this repository |
| Custom-domain Login V2 | NOT VERIFIED | No custom-domain configuration or environment exists in this repository |

## Security boundary

ZITADEL remains the authentication authority.

Marketstack Login Service owns the custom authentication ceremony and
ZITADEL Session API orchestration.

SaaS-OS remains the OIDC relying party and owns:
- OIDC callback
- PKCE/state/nonce
- ID-token validation
- SaaS-OS session
- tenant resolution
- RBAC/authorization
- application logout

The verification found:
- No SaaS-OS credential-handling path introduced.
- No direct Login Service → SaaS-OS authentication coupling introduced.

This architecture is unchanged by this document. Any change to it is an
ADR-0017 decision, not something this verification record can alter.

## Remaining limitations

Successful authentication was not completed because no existing local
test account with known credentials was available, and creating one was
outside the scope of the verification. Consequently, the following
remain unverified in any environment:

- successful password login
- OIDC callback after successful login
- authenticated SaaS-OS session
- tenant resolution
- RBAC authorization
- authenticated logout
- live MFA
- live WebAuthn

None of the above are known defects — the code paths involved are
covered by the Login Service's own test suite (executed and passing at
the time of this record) and by static inspection of the implementation.
They are simply not independently confirmed by a live, real, successful
authentication in this environment.

## Production / custom-domain verification

Production Login V2 verification and custom-domain Login V2 verification
are both **NOT VERIFIED**, and must remain distinct from the local
verification recorded above: no production environment, production
credentials, or custom-domain configuration exist anywhere in this
repository. Local verification success must never be read as implying
production or custom-domain readiness.

## Next verification prerequisite

A dedicated authenticated test environment/account is required before
the remaining end-to-end authenticated flow (successful login → OIDC
callback → SaaS-OS session → tenant resolution → RBAC → authenticated
logout, plus live TOTP/MFA and live WebAuthn) can be verified.

Production/custom-domain verification requires an explicitly authorized
production-like environment and must not be inferred from local
verification.

This document does not create that environment, and does not recommend
weakening any existing security boundary in order to enable testing.

## Relationship to ADR-0017

- ADR-0017 remains the architectural decision.
- This document records verification evidence against that decision.
- This document does not supersede or modify ADR-0017.
- Local verification, as recorded here, does not constitute production
  approval.
