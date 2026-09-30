"use client";

// The global, read-only platform plan catalog (`GET /v1/billing/plans`) --
// distinct from a tenant's own resale plans (`ResalePlansPanel`): this is
// the platform's own catalog, never authored or edited from this product.
import { listPlans } from "@/lib/api/billing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export function PlansCatalog() {
  const query = useApiQuery(() => listPlans(), []);

  if (query.status === "loading") return <LoadingState label="Loading platform plans…" />;
  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }
  if (query.data.length === 0) {
    return <EmptyState title="No platform plans" description="No platform plan is published yet." />;
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-3)" }}>
      {query.data.map((plan) => (
        <Card key={plan.key} style={{ minWidth: 220, flex: "1 1 220px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginBottom: "var(--space-2)" }}>
            <h3 style={{ margin: 0, fontSize: "var(--font-size-md)" }}>{plan.name}</h3>
            <Badge tone="neutral">{plan.key}</Badge>
          </div>
          {Object.keys(plan.entitlements).length === 0 ? (
            <p style={{ margin: 0, color: "var(--color-text-muted)", fontSize: "var(--font-size-sm)" }}>
              No entitlements listed.
            </p>
          ) : (
            <dl style={{ margin: 0, display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
              {Object.entries(plan.entitlements).map(([key, value]) => (
                <div key={key} style={{ display: "flex", justifyContent: "space-between", gap: "var(--space-2)", fontSize: "var(--font-size-sm)" }}>
                  <dt style={{ color: "var(--color-text-muted)" }}>{key}</dt>
                  <dd style={{ margin: 0 }}>{String(value)}</dd>
                </div>
              ))}
            </dl>
          )}
        </Card>
      ))}
    </div>
  );
}
