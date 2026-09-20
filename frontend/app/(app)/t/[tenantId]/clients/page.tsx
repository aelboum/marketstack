"use client";

// Agency/Client management (Phase 3) -- treats the current tenant (from
// the URL, via useTenant()) as the agency whose clients this lists. If
// this tenant isn't reachable as an agency for the signed-in actor (a
// plain client-tenant member, or someone with no `agency.client:read`
// here), `ClientsList` renders the same non-enumerating
// PermissionDeniedState any other UI-2 view would -- this page invents
// no "you're not an agency owner" message the backend itself never says.
import { useState } from "react";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { ClientsList, CreateClientForm } from "@/components/agency";

export default function ClientsPage() {
  const { tenantId } = useTenant();
  const [reloadKey, setReloadKey] = useState(0);

  return (
    <Page>
      <PageHeader
        title="Clients"
        description="Client tenants under this agency, and their invitation/onboarding status."
      />

      <Card style={{ marginBottom: "var(--space-4)" }}>
        <h2 style={{ marginTop: 0, fontSize: "var(--font-size-md)" }}>Create a client</h2>
        <CreateClientForm
          agencyTenantId={tenantId}
          onCreated={() => setReloadKey((key) => key + 1)}
        />
      </Card>

      <ClientsList agencyTenantId={tenantId} reloadKey={reloadKey} />
    </Page>
  );
}
