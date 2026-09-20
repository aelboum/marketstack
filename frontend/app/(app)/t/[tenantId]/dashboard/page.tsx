"use client";

// The real agency dashboard (UI-2, replacing UI-1's placeholder). Still
// renders no fabricated metrics (revenue, MRR, conversion rates, ... --
// UI-2 scope item 20): the one number on this page (client count) comes
// directly from a real API response, everything else is either the
// known tenant id (from the URL) or a link into a module that either
// already has real data (Clients) or is still its own future UI phase's
// placeholder (CRM/Conversations/Marketing/Appointments, unchanged from
// UI-1). There is no endpoint to fetch this tenant's own name
// (documented gap -- no `GET /v1/agency/tenants/{tenantId}` or
// equivalent exists), so this page never shows one.
import { useState } from "react";
import Link from "next/link";
import { useSession } from "@/lib/auth/session-context";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { ClientsList, InviteMemberPanel } from "@/components/agency";
import { NAV_ITEMS } from "@/lib/nav/config";

export default function DashboardPage() {
  const { user } = useSession();
  const { tenantId } = useTenant();
  const [inviteOpen, setInviteOpen] = useState(false);

  const availableModules = NAV_ITEMS.filter(
    (item) => item.status === "available" && item.segment !== "dashboard" && item.segment !== "clients",
  );

  return (
    <Page>
      <PageHeader
        title="Dashboard"
        description={`Signed in as ${user?.user_id ?? "—"} · Tenant ${tenantId}`}
        actions={<Button onClick={() => setInviteOpen(true)}>Invite teammate</Button>}
      />

      <section aria-labelledby="clients-heading" style={{ marginBottom: "var(--space-5)" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "var(--space-2)",
          }}
        >
          <h2 id="clients-heading" style={{ fontSize: "var(--font-size-md)", margin: 0 }}>
            Clients
          </h2>
          <Link href={`/t/${tenantId}/clients`} style={{ fontSize: "var(--font-size-sm)" }}>
            Manage clients →
          </Link>
        </div>
        <ClientsList
          agencyTenantId={tenantId}
          limit={5}
          emptyAction={
            <Link href={`/t/${tenantId}/clients`}>
              <Button size="sm">Create your first client</Button>
            </Link>
          }
        />
      </section>

      <section aria-label="Other modules">
        <h2 style={{ fontSize: "var(--font-size-md)" }}>Modules</h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: "var(--space-3)",
          }}
        >
          {availableModules.map((item) => (
            <Card key={item.key}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: "var(--space-2)",
                }}
              >
                <strong>{item.label}</strong>
                <Badge tone="success">Available</Badge>
              </div>
              <p
                style={{
                  margin: "0 0 var(--space-3)",
                  color: "var(--color-text-muted)",
                  fontSize: "var(--font-size-sm)",
                }}
              >
                Backed by the real Product API.
              </p>
              <Link
                href={`/t/${tenantId}/${item.segment}`}
                style={{ fontSize: "var(--font-size-sm)" }}
              >
                Open {item.label} →
              </Link>
            </Card>
          ))}
        </div>
      </section>

      <Dialog open={inviteOpen} onClose={() => setInviteOpen(false)} title="Invite a teammate">
        <InviteMemberPanel tenantId={tenantId} />
      </Dialog>
    </Page>
  );
}
