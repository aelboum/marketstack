"use client";

// Manually records a review -- `POST .../reviews`. `provider` is always
// `"manual"`: `product/reputation/providers.py`'s own module docstring
// says Phase 12.2 (a real provider adapter/import) is deliberately
// deferred, so this is the only way a review can be recorded today.
//
// `review_request_id` is optional and, when set, must reference one of
// this tenant's own `sent` requests (`product/reputation/reviews.py`'s
// own module docstring) -- offered as a select over the first 100 `sent`
// requests, the same "reference data" convenience pattern as the contact
// picker in `CreateReviewRequestForm`.
import { useEffect, useState } from "react";
import { listReviewRequests, recordReview, type Review, type ReviewRequest } from "@/lib/api/reputation";
import { MAX_AUTHOR_NAME_LENGTH, MAX_REVIEW_BODY_LENGTH, MAX_RATING, MIN_RATING } from "@/lib/reputation/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

const RATINGS = [1, 2, 3, 4, 5];

export function RecordReviewForm({
  tenantId,
  onSaved,
}: {
  tenantId: string;
  onSaved: (review: Review) => void;
}) {
  const [sentRequests, setSentRequests] = useState<ReviewRequest[]>([]);
  const [rating, setRating] = useState(5);
  const [authorName, setAuthorName] = useState("");
  const [body, setBody] = useState("");
  const [reviewRequestId, setReviewRequestId] = useState("");

  useEffect(() => {
    let cancelled = false;
    listReviewRequests(tenantId, { limit: 100 }).then((page) => {
      if (!cancelled) setSentRequests(page.results.filter((r) => r.status === "sent"));
    });
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  const { state, run } = useAsyncAction(() =>
    recordReview(tenantId, {
      rating,
      author_name: authorName,
      body: body.trim() ? body : undefined,
      review_request_id: reviewRequestId || undefined,
    }),
  );

  const nameTooLong = authorName.length > MAX_AUTHOR_NAME_LENGTH;
  const bodyTooLong = body.length > MAX_REVIEW_BODY_LENGTH;
  const canSubmit = authorName.trim().length > 0 && !nameTooLong && !bodyTooLong;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const created = await run();
        if (created) onSaved(created);
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>Rating</span>
        <select
          value={rating}
          onChange={(event) => setRating(Number(event.target.value))}
          aria-label="Rating"
        >
          {RATINGS.filter((r) => r >= MIN_RATING && r <= MAX_RATING).map((r) => (
            <option key={r} value={r}>
              {r} out of 5
            </option>
          ))}
        </select>
      </label>

      <Input
        label="Author name"
        required
        value={authorName}
        onChange={(event) => setAuthorName(event.target.value)}
        error={nameTooLong ? `Author name must be ${MAX_AUTHOR_NAME_LENGTH} characters or fewer.` : undefined}
      />

      <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
        <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
          Review text (optional)
        </span>
        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={4}
          aria-label="Review text"
          style={{
            fontFamily: "inherit",
            fontSize: "var(--font-size-sm)",
            padding: "var(--space-2)",
            border: `1px solid ${bodyTooLong ? "var(--color-danger)" : "var(--color-border-strong)"}`,
            borderRadius: "var(--radius-sm)",
          }}
        />
        {bodyTooLong ? (
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-danger)" }} role="alert">
            Review text must be {MAX_REVIEW_BODY_LENGTH} characters or fewer.
          </span>
        ) : null}
      </label>

      {sentRequests.length > 0 ? (
        <label style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)" }}>
          <span style={{ fontSize: "var(--font-size-xs)", color: "var(--color-text-muted)" }}>
            Link to a sent request (optional)
          </span>
          <select
            value={reviewRequestId}
            onChange={(event) => setReviewRequestId(event.target.value)}
          >
            <option value="">None</option>
            {sentRequests.map((r) => (
              <option key={r.id} value={r.id}>
                Request sent {r.sent_at ? new Date(r.sent_at).toLocaleDateString() : ""}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Recording…" : "Record review"}
      </Button>
    </form>
  );
}
