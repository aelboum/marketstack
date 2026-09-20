"use client";

// Recipients -- `GET .../campaigns/{id}/recipients`, pagination-only,
// read-only (no per-recipient action exists on this router).
import { useState } from "react";
import { listCampaignRecipients, type CampaignRecipient, type RecipientStatus } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<RecipientStatus, "neutral" | "accent" | "success" | "danger" | "warning"> = {
  pending: "neutral",
  sent: "success",
  suppressed: "warning",
  failed: "danger",
};

export function CampaignRecipientsList({ tenantId, campaignId }: { tenantId: string; campaignId: string }) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listCampaignRecipients(tenantId, campaignId, { limit: PAGE_SIZE, offset }),
    [tenantId, campaignId, offset],
  );

  if (query.status === "loading") return <LoadingState label="Loading recipients…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return <EmptyState title="No recipients yet" description="Recipients appear here once this campaign has been sent." />;
  }

  const columns: DataTableColumn<CampaignRecipient>[] = [
    { key: "contact", header: "Contact", render: (r) => r.contact_id ?? "—" },
    { key: "status", header: "Status", render: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge> },
    { key: "sent_at", header: "Sent at", render: (r) => (r.sent_at ? new Date(r.sent_at).toLocaleString() : "—") },
    { key: "error", header: "Error", render: (r) => r.error ?? "—" },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable columns={columns} rows={query.data.results} rowKey={(r) => r.id} />
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
