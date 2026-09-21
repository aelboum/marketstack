"use client";

// Review detail. Composes the review's own identity/rating, its posted
// responses, and the form to post another -- separately-fetched
// resources (the review endpoint does not embed its responses).
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { getReview } from "@/lib/api/reputation";
import { useApiQuery } from "@/lib/hooks/useApiQuery";
import { Page } from "@/components/shell/Page";
import { PageHeader } from "@/components/ui/PageHeader";
import { LoadingState } from "@/components/ui/states";
import { ApiErrorPanel } from "@/components/ui/ApiErrorPanel";
import { InlineNotice } from "@/components/ui/InlineNotice";
import { ReviewDetailCard, ReviewResponsesList, RespondToReviewForm } from "@/components/reputation";

export default function ReviewDetailPage() {
  const { tenantId, reviewId } = useParams<{ tenantId: string; reviewId: string }>();
  const [responsesReloadKey, setResponsesReloadKey] = useState(0);
  const [postedNotice, setPostedNotice] = useState(false);

  const reviewQuery = useApiQuery(() => getReview(tenantId, reviewId), [tenantId, reviewId, responsesReloadKey]);

  if (reviewQuery.status === "loading") {
    return (
      <Page>
        <LoadingState label="Loading review…" />
      </Page>
    );
  }
  if (reviewQuery.status === "error") {
    return (
      <Page>
        <ApiErrorPanel error={reviewQuery.error} onRetry={reviewQuery.refetch} />
      </Page>
    );
  }

  const review = reviewQuery.data;

  return (
    <Page>
      <p style={{ marginTop: 0 }}>
        <Link href={`/t/${tenantId}/reputation`} style={{ fontSize: "var(--font-size-sm)" }}>
          ← Back to reputation
        </Link>
      </p>
      <PageHeader title={`Review from ${review.author_name}`} />

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
        <section aria-labelledby="detail-heading">
          <h2 id="detail-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Details
          </h2>
          <ReviewDetailCard review={review} />
        </section>

        <section aria-labelledby="responses-heading">
          <h2 id="responses-heading" style={{ fontSize: "var(--font-size-md)" }}>
            Responses
          </h2>
          <div style={{ marginBottom: "var(--space-3)" }}>
            <RespondToReviewForm
              tenantId={tenantId}
              reviewId={review.id}
              onSent={() => {
                setPostedNotice(true);
                setResponsesReloadKey((key) => key + 1);
              }}
            />
            {postedNotice ? (
              <div style={{ marginTop: "var(--space-2)" }}>
                <InlineNotice tone="success" onDismiss={() => setPostedNotice(false)}>
                  Response posted.
                </InlineNotice>
              </div>
            ) : null}
          </div>
          <ReviewResponsesList tenantId={tenantId} reviewId={review.id} reloadKey={responsesReloadKey} />
        </section>
      </div>
    </Page>
  );
}
