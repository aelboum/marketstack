"use client";

// The dashboard shell (UI-1 scope: "a dashboard shell (no real dashboard
// data yet)"). Deliberately renders no metrics/KPIs -- the backend has
// no dashboard-summary endpoint, and UI-1 must not fabricate one
// (per-module real data is UI-2 (Agency/Dashboard) through UI-6's job).
// What it does do: prove the shell/session/tenant foundation actually
// works, and orient the user toward the modules that already have real
// backend functionality behind them.
import { useSession } from "@/lib/auth/session-context";
import { useTenant } from "@/lib/tenant/tenant-context";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import Link from "next/link";
import { NAV_ITEMS } from "@/lib/nav/config";

export default function DashboardPage() {
  const { user } = useSession();
  const { tenantId } = useTenant();

  const availableModules = NAV_ITEMS.filter(
    (item) => item.status === "available" && item.segment !== "dashboard",
  );

  return (
    <Page>
      <PageHeader
        title="Dashboard"
        description={`Signed in as ${user?.user_id ?? "—"} · Tenant ${tenantId}`}
      />

      <section
        aria-label="Available modules"
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
            <Link href={`/t/${tenantId}/${item.segment}`} style={{ fontSize: "var(--font-size-sm)" }}>
              Open {item.label} →
            </Link>
          </Card>
        ))}
      </section>
    </Page>
  );
}
