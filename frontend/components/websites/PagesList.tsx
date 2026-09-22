"use client";

// Page list for one website -- `GET .../websites/{id}/pages`, `limit`/
// `offset` only. Status shown as text + badge (never color alone, UI-8
// convention) -- exactly the two real states,
// `product/websites/pages.py`'s own module docstring: "no archived, no
// scheduled, no pending review."
import { useState } from "react";
import { listPages, type WebsitePage, type WebsitePageStatus } from "@/lib/api/websites";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<WebsitePageStatus, "neutral" | "success"> = {
  draft: "neutral",
  published: "success",
};

export function PagesList({
  tenantId,
  websiteId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  websiteId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listPages(tenantId, websiteId, { limit: PAGE_SIZE, offset }),
    [tenantId, websiteId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading pages…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No pages yet"
        description="Pages created on this website will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<WebsitePage>[] = [
    { key: "title", header: "Title", render: (p) => p.title },
    { key: "slug", header: "Slug", render: (p) => p.slug },
    {
      key: "status",
      header: "Status",
      render: (p) => <Badge tone={STATUS_TONE[p.status]}>{p.status}</Badge>,
    },
    {
      key: "published",
      header: "Published",
      render: (p) => (p.published_at ? new Date(p.published_at).toLocaleString() : "—"),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(p) => p.id}
        getRowHref={(p) => `/t/${tenantId}/websites/${websiteId}/pages/${p.id}`}
        label="Pages"
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
