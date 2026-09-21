"use client";

// The review's own top-level fields. No edit/delete here -- the backend
// defines create/list/get only for a `Review` (`product/reputation/
// routes.py`'s own route set); a review is an immutable record of what a
// customer said, not something this UI can rewrite.
import { type Review, type ReviewStatus } from "@/lib/api/reputation";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";

const STATUS_TONE: Record<ReviewStatus, "accent" | "success"> = {
  new: "accent",
  responded: "success",
};

function Rating({ rating }: { rating: number }) {
  return (
    <span aria-hidden="true" title={`${rating} out of 5`}>
      {"★".repeat(rating)}
      {"☆".repeat(5 - rating)}
    </span>
  );
}

export function ReviewDetailCard({ review }: { review: Review }) {
  return (
    <Card>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          marginBottom: "var(--space-3)",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-1)" }}>
          <Rating rating={review.rating} />
          <strong>{review.rating}/5</strong>
        </span>
        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <Badge tone="neutral">{review.provider}</Badge>
          <Badge tone={STATUS_TONE[review.status]}>{review.status}</Badge>
        </div>
      </div>

      <dl
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: "var(--space-1) var(--space-3)",
          margin: 0,
          fontSize: "var(--font-size-sm)",
        }}
      >
        <dt style={{ color: "var(--color-text-muted)" }}>Author</dt>
        <dd style={{ margin: 0 }}>{review.author_name}</dd>
        <dt style={{ color: "var(--color-text-muted)" }}>Received</dt>
        <dd style={{ margin: 0 }}>{new Date(review.received_at).toLocaleString()}</dd>
      </dl>

      {review.body ? (
        <p style={{ marginTop: "var(--space-3)", marginBottom: 0, whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {review.body}
        </p>
      ) : null}
    </Card>
  );
}
