"use client";

// Workflow list -- `GET .../durable/tenants/{t}/workflows`, `limit`/
// `offset` only (no filter exists on this endpoint), the same
// pagination-only shape every other filter-less list in this product
// already uses.
//
// Trigger/action are shown from the workflow's own fields where
// present. A workflow created outside this UI can have no published
// version at all (`current_published_version_id: null`) -- shown as
// "No published version" rather than guessing at a trigger/action this
// list endpoint does not return (the workflow list response has no
// trigger/action fields; those live on a version, fetched only when a
// row is opened).
import { useState } from "react";
import { listWorkflows, type Workflow, type WorkflowStatus } from "@/lib/api/automation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<WorkflowStatus, "success" | "neutral"> = {
  active: "success",
  paused: "neutral",
};

export function WorkflowsList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listWorkflows(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading automations…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No automations yet"
        description="Automations created for this tenant will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Workflow>[] = [
    { key: "name", header: "Name", render: (w) => w.name },
    {
      key: "status",
      header: "Status",
      render: (w) => <Badge tone={STATUS_TONE[w.status]}>{w.status}</Badge>,
    },
    {
      key: "published",
      header: "Published version",
      render: (w) =>
        w.current_published_version_id ? (
          <Badge tone="accent">Published</Badge>
        ) : (
          <Badge tone="neutral">Draft only</Badge>
        ),
    },
    { key: "updated", header: "Updated", render: (w) => new Date(w.updated_at).toLocaleString() },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(w) => w.id}
        getRowHref={(w) => `/t/${tenantId}/automation/${w.id}`}
        label="Automations"
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
