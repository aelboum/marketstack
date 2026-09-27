// Thin wrapper over the saas-os-provided /auth/* routes (mounted by
// api.platform.build_platform_app(), product/api/main.py). This product
// never implements its own authentication logic -- see
// docs/ROADMAP.md Phase 1.6 and docs/ARCHITECTURE.md §6.1.

import { API_BASE_URL } from "@/lib/api/config";
import { request } from "@/lib/api/client";

export type CurrentUser = {
  /** Matches CurrentUserResponse in the backend's OpenAPI schema --
   * deliberately just the stable user id; which tenants this user may
   * act in is answered per-tenant by the backend's own membership-checked
   * routes, not by this endpoint (see /auth/me's own docstring). */
  user_id: string;
};

export function getCurrentUser(signal?: AbortSignal): Promise<CurrentUser> {
  return request<CurrentUser>("/auth/me", { signal });
}

/**
 * Product logout has two independent responsibilities that must both run
 * on every logout (security audit F-05): SaaS-OS's own `/auth/logout`
 * (clears `product_session`) and the product-owned Login Service's
 * `/login-svc/logout` (deletes the underlying ZITADEL session and clears
 * its own, separately-scoped cookies -- see login-service/app/main.py's
 * own `logout()` docstring). Neither call needs the other's cookie: they
 * are scoped to disjoint paths (`/auth/*` vs `/login-svc/*`), and the
 * browser attaches each one only to matching requests on its own -- this
 * function never reads, forwards, or otherwise touches either cookie's
 * value.
 *
 * The Login Service call is fired via a plain `fetch()`, not `request()`
 * -- it targets a different service than "the Product backend" this
 * module's sibling functions call (see lib/api/client.ts's own docstring
 * on what `request()` is for), and its failure must never surface any
 * differently than before this call existed: a network error is
 * swallowed here, and a non-2xx status does not reject `fetch()` at all.
 * Both calls are attempted regardless of the other's outcome, and this
 * function waits for both to settle before returning, so the ZITADEL
 * session deletion round-trip has actually completed by the time a
 * caller (e.g. a post-logout redirect) proceeds.
 */
export async function logout(): Promise<void> {
  const loginServiceLogout = fetch(`${API_BASE_URL}/login-svc/logout`, {
    method: "POST",
    credentials: "include",
  }).catch(() => {
    // Network/CORS failure reaching the Login Service must never block
    // the rest of logout -- see this function's own docstring.
  });

  try {
    await request<void>("/auth/logout", { method: "POST" });
  } finally {
    await loginServiceLogout;
  }
}

/** Full-page navigation target -- the OIDC redirect flow is a real
 * browser navigation, not a fetch, so it is exempt from the CORS gap
 * documented in lib/api/client.ts. */
export function loginUrl(): string {
  return `${API_BASE_URL}/auth/login`;
}
