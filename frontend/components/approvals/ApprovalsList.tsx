"use client";

// The Approval Inbox list (docs/ROADMAP.md Phase 29). Every column is
// already business language at the wire level (`action_label`/
// `status_label`, `product/approvals/labels.py`) -- this component never
// re-translates a raw `tool_key`/`status` itself.
import { listApprovals, type Approval } from "@/lib/api/approvals";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { Badge } from "@/components/ui/Badge";

function statusTone(status: Approval["status"]): "neutral" | "success" | "warning" | "danger" {
  switch (status) {
    case "pending":
      return "warning";
    case "approved":
    case "executing":
      return "neutral";
    case "executed":
      return "success";
    case "rejected":
      return "danger";
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ApprovalsList({
  tenantId,
  reloadKey,
}: {
  tenantId: string;
  reloadKey?: unknown;
}) {
  const query = useApiQuery(() => listApprovals(tenantId, { status: "pending" }), [
    tenantId,
    reloadKey,
  ]);

  if (query.status === "loading") {
    return <LoadingState label="Goedkeuringen laden…" />;
  }

  if (query.status === "error") {
    return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  }

  const approvals = query.data;

  if (approvals.length === 0) {
    return (
      <EmptyState
        title="Niets om te beoordelen"
        description="Er zijn momenteel geen acties die op goedkeuring wachten."
      />
    );
  }

  const columns: DataTableColumn<Approval>[] = [
    { key: "action", header: "Actie", render: (row) => row.action_label },
    { key: "created", header: "Aangevraagd", render: (row) => formatDate(row.created_at) },
    {
      key: "status",
      header: "Status",
      render: (row) => <Badge tone={statusTone(row.status)}>{row.status_label}</Badge>,
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={approvals}
      rowKey={(row) => row.id}
      getRowHref={(row) => `/t/${tenantId}/approvals/${row.id}`}
      label="Goedkeuringen"
    />
  );
}
