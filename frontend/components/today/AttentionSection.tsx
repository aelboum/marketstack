"use client";

// "Needs your attention" -- the Command Center's own top section
// (docs/ROADMAP.md Phase 28). Real data only: failed automation runs,
// composed from the existing Automation API
// (lib/dashboard/commandCenter.ts::loadAutomationActivity()). No
// fabricated count, no placeholder severity -- a tenant with zero failed
// runs sees an honest empty state, not a hidden or invented "0".
import { loadAutomationActivity } from "@/lib/dashboard/commandCenter";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

export function AttentionSection({ tenantId }: { tenantId: string }) {
  const query = useApiQuery(() => loadAutomationActivity(tenantId), [tenantId]);

  if (query.status === "loading") {
    return <LoadingState label="Aandachtspunten laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const { failed } = query.data;

  if (failed.length === 0) {
    return (
      <EmptyState
        title="Alles in orde"
        description="Er zijn momenteel geen automatiseringen die mislukt zijn en uw aandacht nodig hebben."
      />
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }} data-testid="attention-list">
      {failed.map((run) => (
        <Card key={run.id}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "var(--space-3)",
            }}
          >
            <div>
              <strong>{run.workflowName}</strong>
              <div style={{ fontSize: "var(--font-size-sm)", color: "var(--color-text-muted)" }}>
                {run.error ?? "Deze automatisering is mislukt."}
              </div>
            </div>
            <Badge tone="danger">Mislukt</Badge>
          </div>
        </Card>
      ))}
    </div>
  );
}
