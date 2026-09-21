"use client";

// Responses posted to one review -- `GET .../reviews/{id}/responses`,
// `limit`/`offset`. The backend's own `list_responses()` orders by
// `created_at asc` (oldest first, a conversation reads top-to-bottom),
// rendered as-is.
import { listReviewResponses } from "@/lib/api/reputation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { LoadingState, EmptyState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { Card } from "@/components/ui/Card";

export function ReviewResponsesList({
  tenantId,
  reviewId,
  reloadKey,
}: {
  tenantId: string;
  reviewId: string;
  reloadKey?: unknown;
}) {
  const query = useApiQuery(
    () => listReviewResponses(tenantId, reviewId, { limit: 25, offset: 0 }),
    [tenantId, reviewId, reloadKey],
  );

  if (query.status === "loading") return <LoadingState label="Loading responses…" />;
  if (query.status === "error") return <ApiErrorPanel error={query.error} onRetry={query.refetch} />;
  if (query.data.results.length === 0) {
    return <EmptyState title="No responses yet" description="A posted response will appear here." />;
  }

  return (
    <ol style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
      {query.data.results.map((responseItem) => (
        <li key={responseItem.id}>
          <Card>
            <p style={{ margin: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{responseItem.body}</p>
            <p style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-xs)", color: "var(--color-text-faint)" }}>
              {new Date(responseItem.created_at).toLocaleString()}
            </p>
          </Card>
        </li>
      ))}
    </ol>
  );
}
