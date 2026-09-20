"use client";

// Tenant/agency context foundation (UI-1 scope). The active tenant id
// comes from the URL (`/t/[tenantId]/...`, matching how the backend's
// own routes are already tenant_id-scoped in their path --
// product/crm/routes.py etc.), not from a client-side "current tenant"
// guess. This context exists so any component under the shell can read
// the active tenant id without threading it through props, and so a
// switch to a different tenant is always a navigation (a new
// `tenant_id`, re-checked by the backend on every call), never a
// client-side flag flip. See lib/tenant/last-tenant.ts for the
// documented reason UI-1 does not offer a real tenant *switcher* yet.

import { createContext, useContext, useEffect, useMemo } from "react";
import { setLastTenantId } from "@/lib/tenant/last-tenant";

export type TenantState = {
  tenantId: string;
};

const TenantContext = createContext<TenantState | null>(null);

export function TenantProvider({
  tenantId,
  children,
}: {
  tenantId: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    setLastTenantId(tenantId);
  }, [tenantId]);

  const value = useMemo(() => ({ tenantId }), [tenantId]);

  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

/** Throws outside a tenant-scoped route -- callers that must also work
 * on a non-tenant-scoped page should use `useOptionalTenant()` instead. */
export function useTenant(): TenantState {
  const context = useContext(TenantContext);
  if (!context) {
    throw new Error("useTenant() must be called inside a <TenantProvider>.");
  }
  return context;
}

export function useOptionalTenant(): TenantState | null {
  return useContext(TenantContext);
}
