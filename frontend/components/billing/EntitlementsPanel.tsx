"use client";

// Informational display of `GET .../entitlements` -- the backend remains
// the sole enforcement point for every entitlement (UI-14's own scope);
// this panel never recomputes or duplicates that decision, it only shows
// what the backend already returned.
import { getEntitlements } from "@/lib/api/billing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";

export function EntitlementsPanel({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => getEntitlements(tenantId), [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading entitlements…" />;
  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const entries = Object.entries(query.data);
  if (entries.length === 0) {
    return (
      <EmptyState
        title="No entitlements"
        description="This workspace has no effective entitlements from its current subscription."
      />
    );
  }

  return (
    <dl style={{ margin: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {entries.map(([key, value]) => (
        <div
          key={key}
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: "var(--space-3)",
            fontSize: "var(--font-size-sm)",
            paddingBottom: "var(--space-2)",
            borderBottom: "1px solid var(--color-border)",
          }}
        >
          <dt>{key}</dt>
          <dd style={{ margin: 0, color: "var(--color-text-muted)" }}>
            {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
