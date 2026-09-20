"use client";

// Campaign list -- `GET .../campaigns`, `limit`/`offset` only (no `q`,
// channel, or status filter exists on this endpoint -- verified by
// reading `product/marketing/routes.py::list_campaigns_route`), so this
// is pagination-only, the same shape UI-4's `ThreadsList` already
// established for an equally filter-less backend list.
import { useState } from "react";
import { listCampaigns, type Campaign, type CampaignStatus } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<CampaignStatus, "neutral" | "accent" | "success" | "danger" | "warning"> = {
  draft: "neutral",
  sending: "accent",
  sent: "success",
  cancelled: "warning",
  failed: "danger",
};

export function CampaignsList({
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
    () => listCampaigns(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading campaigns…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No campaigns yet"
        description="Campaigns created for this tenant will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Campaign>[] = [
    { key: "name", header: "Name", render: (c) => c.name },
    { key: "channel", header: "Channel", render: (c) => <Badge tone="accent">{c.channel}</Badge> },
    { key: "status", header: "Status", render: (c) => <Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge> },
    { key: "updated", header: "Updated", render: (c) => new Date(c.updated_at).toLocaleString() },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(c) => c.id}
        getRowHref={(c) => `/t/${tenantId}/marketing/campaigns/${c.id}`}
      />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
          Showing {offset + 1}–{offset + query.data.results.length}
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)" }}>
          <Button variant="secondary" size="sm" onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))} disabled={offset === 0}>
            Previous
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setOffset((o) => o + PAGE_SIZE)} disabled={!query.data.hasMore}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
