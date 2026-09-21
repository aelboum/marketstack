"use client";

// Review request list -- `GET .../review-requests`, `limit`/`offset` (+
// optional `contact_id`, not used by this hub view). Cancel is offered
// only while `status === "sent"` -- the only status
// `cancel_review_request()` ever accepts
// (`product/reputation/review_requests.py`'s own module docstring); any
// other status the backend would reject with a 400, so this never offers
// a transition it knows is invalid. Whether the *actor* is allowed to
// cancel (owner-only, `product/reputation/event_handlers.py`) is left to
// the backend: this always tries, and a 403/404 surfaces as the normal
// non-enumerating InlineNotice message, never a client-side role check.
import { useState } from "react";
import {
  cancelReviewRequest,
  listReviewRequests,
  type ReviewRequest,
  type RequestStatus,
} from "@/lib/api/reputation";
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

const STATUS_TONE: Record<RequestStatus, "neutral" | "accent" | "success" | "danger" | "warning"> = {
  pending: "neutral",
  sent: "accent",
  failed: "danger",
  cancelled: "warning",
  fulfilled: "success",
};

function CancelCell({
  tenantId,
  reviewRequest,
  onCancelled,
}: {
  tenantId: string;
  reviewRequest: ReviewRequest;
  onCancelled: () => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { run, state } = useAsyncAction(() => cancelReviewRequest(tenantId, reviewRequest.id));

  if (reviewRequest.status !== "sent") return null;

  return (
    <>
      <Button variant="danger" size="sm" onClick={() => setConfirmOpen(true)}>
        Cancel
      </Button>
      <ConfirmDialog
        open={confirmOpen}
        title="Cancel this review request?"
        description="The contact will no longer be able to fulfill this request. This cannot be undone."
        confirmLabel="Cancel request"
        cancelLabel="Keep it"
        danger
        pending={state.status === "pending"}
        onConfirm={async () => {
          const cancelled = await run();
          setConfirmOpen(false);
          if (cancelled) onCancelled();
        }}
        onCancel={() => setConfirmOpen(false)}
      />
      {state.status === "error" ? (
        <div style={{ marginTop: "var(--space-1)" }}>
          <InlineNotice tone="danger">{state.error.message}</InlineNotice>
        </div>
      ) : null}
    </>
  );
}

export function ReviewRequestsList({
  tenantId,
  reloadKey,
  onCreate,
}: {
  tenantId: string;
  reloadKey?: unknown;
  onCreate?: React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const [cancelReloadKey, setCancelReloadKey] = useState(0);
  const query = useApiQuery(
    () => listReviewRequests(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey, cancelReloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading review requests…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No review requests yet"
        description="Requests sent to contacts asking for a review will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<ReviewRequest>[] = [
    {
      key: "status",
      header: "Status",
      render: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>,
    },
    { key: "channel", header: "Channel", render: (r) => r.channel },
    {
      key: "sent",
      header: "Sent",
      render: (r) => (r.sent_at ? new Date(r.sent_at).toLocaleString() : "—"),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (r) =>
        r.status === "failed" && r.failure_reason ? (
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            {r.failure_reason}
          </span>
        ) : (
          "—"
        ),
    },
    {
      key: "actions",
      header: "Actions",
      render: (r) => (
        <CancelCell
          tenantId={tenantId}
          reviewRequest={r}
          onCancelled={() => setCancelReloadKey((k) => k + 1)}
        />
      ),
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(r) => r.id}
        label="Review requests"
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
