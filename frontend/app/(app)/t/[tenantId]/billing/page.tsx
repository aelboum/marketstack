"use client";

// UI-14 -- the tenant-facing UI for the existing Phase 13 Billing/Resale
// backend (`product/billing/routes.py`, mounted under `/v1/billing`).
//
// Four independent sections, not one flattened view (the API returns
// four separate resources): the tenant's own subscription(s), the
// read-only platform plan catalog, this tenant's own resale-plan catalog
// (visible to every tenant; a tenant with no resale-management
// permission simply sees an empty-or-forbidden state from the real
// backend response, never a frontend guess about its own role), and this
// tenant's effective entitlements. See `components/billing/*` for the
// section implementations.
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { PlansCatalog, ResalePlansPanel, SubscriptionsPanel, EntitlementsPanel } from "@/components/billing";

export default function BillingPage() {
  const { tenantId } = useTenant();

  return (
    <Page>
      <PageHeader
        title="Subscription & plans"
        description="Subscription, plans, and entitlements for this workspace."
      />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="subscriptions-heading">
          <h2 id="subscriptions-heading" style={{ fontSize: "var(--font-size-md)", marginBottom: "var(--space-3)" }}>
            Subscription
          </h2>
          <SubscriptionsPanel tenantId={tenantId} />
        </section>

        <section aria-labelledby="entitlements-heading">
          <h2 id="entitlements-heading" style={{ fontSize: "var(--font-size-md)", marginBottom: "var(--space-3)" }}>
            Entitlements
          </h2>
          <EntitlementsPanel tenantId={tenantId} />
        </section>

        <section aria-labelledby="plans-heading">
          <h2 id="plans-heading" style={{ fontSize: "var(--font-size-md)", marginBottom: "var(--space-3)" }}>
            Platform plans
          </h2>
          <PlansCatalog />
        </section>

        <section aria-labelledby="resale-plans-heading">
          <h2 id="resale-plans-heading" style={{ fontSize: "var(--font-size-md)", marginBottom: "var(--space-3)" }}>
            Resale plans
          </h2>
          <ResalePlansPanel tenantId={tenantId} />
        </section>
      </div>
    </Page>
  );
}
