"use client";

// Thread list -- `GET .../threads`, `limit`/`offset` only (no `q`,
// `channel`, or status filter exists on this endpoint -- verified by
// reading `product/conversations/routes.py::list_threads_route`), so
// unlike UI-3's CRM lists there is no search/filter UI here at all,
// only pagination. Contact names are resolved client-side against the
// existing CRM contacts API (`lib/api/crm.ts`) -- the thread response
// itself carries only a raw `contact_id`, no embedded contact.
import { useEffect, useState } from "react";
import { listThreads, type Thread } from "@/lib/api/conversations";
import { listContacts } from "@/lib/api/crm";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

export function ThreadsList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const [contactNames, setContactNames] = useState<Record<string, string>>({});

  const query = useApiQuery(
    () => listThreads(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  useEffect(() => {
    let cancelled = false;
    listContacts(tenantId, { limit: 100 }).then((page) => {
      if (cancelled) return;
      setContactNames(
        Object.fromEntries(page.results.map((c) => [c.id, `${c.first_name} ${c.last_name}`])),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  if (query.status === "loading") return <LoadingState label="Loading conversations…" />;
  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No conversations yet"
        description="Conversations created for this tenant will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Thread>[] = [
    {
      key: "contact",
      header: "Contact",
      render: (t) => (t.contact_id ? (contactNames[t.contact_id] ?? t.contact_id) : "—"),
    },
    { key: "channel", header: "Channel", render: (t) => <Badge tone="accent">{t.channel}</Badge> },
    {
      key: "assigned",
      header: "Assigned",
      render: (t) => (t.assigned_to_user_id ? "Assigned" : "Unassigned"),
    },
    {
      key: "updated",
      header: "Updated",
      render: (t) => new Date(t.updated_at).toLocaleString(),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(t) => t.id}
        getRowHref={(t) => `/t/${tenantId}/conversations/${t.id}`}
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
