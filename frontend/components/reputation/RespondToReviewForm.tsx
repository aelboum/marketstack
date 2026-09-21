"use client";

// Posts a response to a review -- `POST .../reviews/{id}/responses`.
// Posting to the real provider only happens for a non-`manual` review
// (`product/reputation/responses.py`'s own module docstring); every
// review this phase can produce is `manual`, so a response here is
// always simply recorded, never actually delivered anywhere external --
// this form makes no claim otherwise. Flips the review's own `status` to
// `"responded"` server-side, so the caller must refetch the review after
// success (`onSent` is the hook for that).
import { useState } from "react";
import { createReviewResponse, type ReviewResponseRecord } from "@/lib/api/reputation";
import { MAX_RESPONSE_BODY_LENGTH } from "@/lib/reputation/constraints";
import { useAsyncAction } from "@/lib/hooks/useAsyncAction";
import { Button } from "@/components/ui/Button";
import { InlineNotice } from "@/components/ui/InlineNotice";

export function RespondToReviewForm({
  tenantId,
  reviewId,
  onSent,
}: {
  tenantId: string;
  reviewId: string;
  onSent: (response: ReviewResponseRecord) => void;
}) {
  const [body, setBody] = useState("");
  const { state, run } = useAsyncAction(() => createReviewResponse(tenantId, reviewId, { body }));

  const bodyTooLong = body.length > MAX_RESPONSE_BODY_LENGTH;
  const canSubmit = body.trim().length > 0 && !bodyTooLong;

  return (
    <form
      onSubmit={async (event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const created = await run();
        if (created) {
          setBody("");
          onSent(created);
        }
      }}
      style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
    >
      <textarea
        value={body}
        onChange={(event) => setBody(event.target.value)}
        rows={3}
        aria-label="Response"
        placeholder="Write a response to this review…"
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
          Response must be {MAX_RESPONSE_BODY_LENGTH} characters or fewer.
        </span>
      ) : null}
      {state.status === "error" ? (
        <InlineNotice tone="danger">{state.error.message}</InlineNotice>
      ) : null}
      <Button type="submit" disabled={state.status === "pending" || !canSubmit}>
        {state.status === "pending" ? "Posting…" : "Post response"}
      </Button>
    </form>
  );
}
