"use client";

// Runs for one workflow -- `GET .../workflows/{id}/runs`, pagination-
// only (no filter on this endpoint either). Every run shown here is a
// real, product-owned row (`durable.Run`); no raw Temporal id, task
// queue, or execution history is surfaced -- `temporal_workflow_id`
// exists on the row but is not rendered, matching the durable module's
// own "Temporal is an execution substrate, not a product feature" rule.
import { useState } from "react";
import { listRuns, type Run, type RunStatus } from "@/lib/api/automation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<RunStatus, "neutral" | "accent" | "success" | "danger" | "warning"> = {
  queued: "neutral",
  running: "accent",
  waiting: "accent",
  completed: "success",
  failed: "danger",
  cancelled: "warning",
};

export function RunsList({
  tenantId,
  workflowId,
  reloadKey,
}: {
  tenantId: string;
  workflowId: string;
  reloadKey?: unknown;
}) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listRuns(tenantId, workflowId, { limit: PAGE_SIZE, offset }),
    [tenantId, workflowId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading runs…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return <EmptyState title="No runs yet" description="Runs of this automation will appear here." />;
  }

  const columns: DataTableColumn<Run>[] = [
    {
      // Combines status + a real timestamp so the row link this becomes
      // (DataTable wraps only the first column) has a distinguishable
      // accessible name -- a status badge alone repeats across rows.
      key: "run",
      header: "Run",
      render: (r) => (
        <>
          <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>{" "}
          {new Date(r.created_at).toLocaleString()}
        </>
      ),
    },
    {
      key: "started",
      header: "Started",
      render: (r) => (r.started_at ? new Date(r.started_at).toLocaleString() : "Not yet started"),
    },
    {
      key: "completed",
      header: "Completed",
      render: (r) => (r.completed_at ? new Date(r.completed_at).toLocaleString() : "—"),
    },
    { key: "error", header: "Error", render: (r) => r.error ?? "—" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(r) => r.id}
        getRowHref={(r) => `/t/${tenantId}/automation/runs/${r.id}`}
        label="Runs"
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
          Showing {offset + 1}–{offset + query.data.results.length}
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
            disabled={offset === 0}
          >
            Previous
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
            disabled={!query.data.hasMore}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
