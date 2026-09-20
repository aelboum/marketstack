// Tenant-selection is a client-side UX convenience only -- the backend
// stays the sole authority on whether the signed-in user may actually act
// in a given tenant (every /v1/*/tenants/{tenant_id}/... call is checked
// server-side regardless of how the frontend arrived at that id).
//
// Documented backend gap (see docs/ROADMAP.md UI Track "UI as a
// product-validation mechanism" / this phase's final report): there is
// currently no backend endpoint that lists "the tenants this
// authenticated user may act in" (/auth/me intentionally returns only
// user_id -- see that route's own docstring). Until one exists, this
// product cannot render a real tenant switcher (UI-2's stated scope);
// UI-1 only remembers the last tenant id the user was on, as a
// navigation convenience, so returning to `/dashboard` with no tenant in
// the URL can offer to resume there instead of forcing a blank state.

const STORAGE_KEY = "product:last-tenant-id";

export function getLastTenantId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setLastTenantId(tenantId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, tenantId);
  } catch {
    // Storage can be unavailable (private browsing, disabled cookies/
    // storage) -- losing this convenience is not an error worth
    // surfacing to the user.
  }
}
