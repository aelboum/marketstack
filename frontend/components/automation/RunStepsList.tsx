"use client";

// Step-level detail for one run -- `GET .../runs/{id}/steps`, unbounded
// (the backend paginates nothing here; see lib/api/automation.ts).
//
// Distinguishes exactly the states the backend actually returns
// (`running`/`succeeded`/`failed`/`skipped`) and nothing else --
// "pending" is not a real step status (a step that has not started yet
// simply has no row here at all), so this never invents one.
import { listRunSteps, type RunStep, type StepRunStatus } from "@/lib/api/automation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { InlineNotice } from "@/components/ui/InlineNotice";

const STATUS_TONE: Record<StepRunStatus, "accent" | "success" | "danger" | "neutral"> = {
  running: "accent",
  succeeded: "success",
  failed: "danger",
  skipped: "neutral",
};

export function RunStepsList({ tenantId, runId }: { tenantId: string; runId: string }) {
  const query = useApiQuery(() => listRunSteps(tenantId, runId), [tenantId, runId]);

  if (query.status === "loading") return <LoadingState label="Loading steps…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.length === 0) {
    return (
      <EmptyState
        title="No step detail yet"
        description="Step-by-step detail appears once this run starts executing."
      />
    );
  }

  return (
    <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {query.data.map((step: RunStep) => (
        <li key={step.id}>
          <Card>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "var(--space-2)",
                flexWrap: "wrap",
              }}
            >
              <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
                <Badge tone={STATUS_TONE[step.status]}>{step.status}</Badge>
                <strong style={{ fontSize: "var(--font-size-sm)" }}>{step.step_key}</strong>
                <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
                  {step.step_type}
                </span>
              </div>
              <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
                {new Date(step.started_at).toLocaleString()}
                {step.completed_at ? ` – ${new Date(step.completed_at).toLocaleTimeString()}` : ""}
              </span>
            </div>
            {step.error ? (
              <div style={{ marginTop: "var(--space-2)" }}>
                <InlineNotice tone="danger">{step.error}</InlineNotice>
              </div>
            ) : null}
          </Card>
        </li>
      ))}
    </ol>
  );
}
