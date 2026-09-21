"use client";

// Review list -- `GET .../reviews`, `limit`/`offset` only (no filter on
// this endpoint, same "pagination-only" shape as `WorkflowsList`). The
// backend's own `list_reviews()` orders by `received_at desc`, so the
// most recent review is always first -- this renders that order as-is,
// never re-sorts client-side.
import { useState } from "react";
import { listReviews, type Review, type ReviewStatus } from "@/lib/api/reputation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { DataTable, type DataTableColumn } from "@/components/ui/DataTable";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<ReviewStatus, "accent" | "success"> = {
  new: "accent",
  responded: "success",
};

/** Star glyphs only ever describe the number, never replace it -- rating
 * is also stated as plain text so it is never color/shape-only. */
function Rating({ rating }: { rating: number }) {
  return (
    <span aria-hidden="true" title={`${rating} out of 5`}>
      {"★".repeat(rating)}
      {"☆".repeat(5 - rating)}
    </span>
  );
}

export function ReviewsList({
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
    () => listReviews(tenantId, { limit: PAGE_SIZE, offset }),
    [tenantId, offset, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading reviews…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return (
      <EmptyState
        title="No reviews yet"
        description="Reviews recorded for this tenant will appear here."
        action={onCreate}
      />
    );
  }

  const columns: DataTableColumn<Review>[] = [
    {
      key: "rating",
      header: "Rating",
      render: (r) => (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-1)" }}>
          <Rating rating={r.rating} /> {r.rating}/5
        </span>
      ),
    },
    { key: "author", header: "Author", render: (r) => r.author_name },
    { key: "provider", header: "Provider", render: (r) => <Badge tone="neutral">{r.provider}</Badge> },
    {
      key: "status",
      header: "Status",
      render: (r) => <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>,
    },
    { key: "received", header: "Received", render: (r) => new Date(r.received_at).toLocaleString() },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <DataTable
        columns={columns}
        rows={query.data.results}
        rowKey={(r) => r.id}
        getRowHref={(r) => `/t/${tenantId}/reputation/reviews/${r.id}`}
        label="Reviews"
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
