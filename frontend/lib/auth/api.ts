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

export async function logout(): Promise<void> {
  await request<void>("/auth/logout", { method: "POST" });
}

/** Full-page navigation target -- the OIDC redirect flow is a real
 * browser navigation, not a fetch, so it is exempt from the CORS gap
 * documented in lib/api/client.ts. */
export function loginUrl(): string {
  return `${API_BASE_URL}/auth/login`;
}
