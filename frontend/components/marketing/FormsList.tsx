"use client";

// Forms -- `GET .../forms`, pagination-only, no edit endpoint exists
// (see `lib/api/marketing.ts` module docstring) so each row only links
// to a read-only detail + delete, same as UI-4's conversation threads
// list feeding a detail page with no dedicated "edit thread" route.
import { useState } from "react";
import { listForms, type MarketingForm } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

export function FormsList({ tenantId, reloadKey, onCreate }: { tenantId: string; reloadKey?: unknown; onCreate?: React.ReactNode }) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(() => listForms(tenantId, { limit: PAGE_SIZE, offset }), [tenantId, offset, reloadKey]);

  if (query.status === "loading") return <LoadingState label="Loading forms…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return <EmptyState title="No forms yet" description="Lead-capture forms created for this tenant appear here." action={onCreate} />;
  }

  const columns: DataTableColumn<MarketingForm>[] = [
    { key: "name", header: "Name", render: (f) => f.name },
    { key: "fields", header: "Fields", render: (f) => f.fields.length },
    { key: "updated", header: "Updated", render: (f) => new Date(f.updated_at).toLocaleString() },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(f) => f.id}
        getRowHref={(f) => `/t/${tenantId}/marketing/forms/${f.id}`}
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
