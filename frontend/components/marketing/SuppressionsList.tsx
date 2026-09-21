"use client";

// Suppressions -- `GET .../suppressions`, pagination-only. Deletion is
// owner-only server-side (`event_handlers.py::_MEMBER_GRANTS` gives
// `member` no `delete` on `marketing.suppression`) -- the control still
// shows for everyone; the real 403/404 (indistinguishable, per this
// product's non-enumeration rule) explains itself through the shared
// `ApiErrorPanel`/InlineNotice, this component makes no client-side
// role guess.
import { useState } from "react";
import { listSuppressions, deleteSuppression, type Suppression } from "@/lib/api/marketing";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/Dialog";
import { InlineNotice } from "@/components/ui/InlineNotice";

const PAGE_SIZE = 25;

function DeleteSuppressionButton({
  tenantId,
  suppression,
  onDeleted,
}: {
  tenantId: string;
  suppression: Suppression;
  onDeleted: () => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run, state } = useAsyncAction(() => deleteSuppression(tenantId, suppression.id));

  return (
    <>
      <Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>
        Remove
      </Button>
      {state.status === "error" ? <InlineNotice tone="danger">{state.error.message}</InlineNotice> : null}
      <ConfirmDialog
        open={confirmOpen}
        title="Remove this suppression?"
        description="This re-subscribes the contact to this channel -- they will be eligible to receive campaigns again."
        confirmLabel="Remove"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          await run();
          setConfirmOpen(false);
          onDeleted();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

export function SuppressionsList({ tenantId, reloadKey, onCreate }: { tenantId: string; reloadKey?: unknown; onCreate?: React.ReactNode }) {
  const [offset, setOffset] = useState(0);
  const query = useApiQuery(
    () => listSuppressions(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading suppressions…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No suppressions yet"
        description="Contacts who unsubscribe, bounce, or are manually suppressed appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Suppression>[] = [
    { key: "contact", header: "Contact", render: (s) => s.contact_id },
    { key: "channel", header: "Channel", render: (s) => <Badge tone="accent">{s.channel}</Badge> },
    { key: "reason", header: "Reason", render: (s) => <Badge>{s.reason}</Badge> },
    { key: "created", header: "Since", render: (s) => new Date(s.created_at).toLocaleString() },
    {
      key: "actions",
      header: "Actions",
      render: (s) => (
        <DeleteSuppressionButton tenantId={tenantId} suppression={s} onDeleted={query.refetch} />
      ),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable columns={columns} rows={query.data.results} rowKey={(s) => s.id} />
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
