"use client";

// Calendar list -- `GET .../calendars`, `limit`/`offset` only (no `q` or
// any filter exists on this endpoint), so this is pagination-only, the
// same shape UI-4's ThreadsList and UI-5's CampaignsList already
// established for equally filter-less backend lists.
import { useState } from "react";
import { listCalendars, type Calendar } from "@/lib/api/appointments";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

export function CalendarsList({
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
    () => listCalendars(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading calendars…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No calendars yet"
        description="A calendar holds its own availability rules and booking link. Create one to start taking appointments."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Calendar>[] = [
    { key: "name", header: "Name", render: (c) => c.name || "(unnamed)" },
    { key: "timezone", header: "Timezone", render: (c) => <Badge tone="accent">{c.timezone}</Badge> },
    { key: "owner", header: "Owner user ID", render: (c) => c.owner_user_id },
    { key: "created", header: "Created", render: (c) => new Date(c.created_at).toLocaleString() },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(c) => c.id}
        getRowHref={(c) => `/t/${tenantId}/appointments/calendars/${c.id}`}
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
