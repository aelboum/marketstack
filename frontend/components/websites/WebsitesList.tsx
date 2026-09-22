"use client";

// Website list -- `GET .../websites`, `limit`/`offset` only (no filter
// exists on this endpoint, the same pagination-only shape every other
// filter-less list in this product already uses).
import { useState } from "react";
import { listWebsites, type Website } from "@/lib/api/websites";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

export function WebsitesList({
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
    () => listWebsites(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading websites…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No websites yet"
        description="Websites created for this tenant will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Website>[] = [
    { key: "name", header: "Name", render: (w) => w.name },
    { key: "slug", header: "Slug", render: (w) => w.slug },
    {
      key: "domain",
      header: "Custom domain",
      render: (w) =>
        w.custom_domain ? w.custom_domain : (
          <Badge tone="neutral">None</Badge>
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
        getRowHref={(w) => `/t/${tenantId}/websites/${w.id}`}
        label="Websites"
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
