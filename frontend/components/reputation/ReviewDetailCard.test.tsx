import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReviewDetailCard } from "./ReviewDetailCard";
import type { Review } from "@/lib/api/reputation";

function review(overrides: Partial<Review> = {}): Review {
  return {
    id: "rev1",
    tenant_id: "t1",
    review_request_id: null,
    provider: "manual",
    external_review_id: null,
    rating: 4,
    author_name: "Jane Doe",
    body: "Would recommend.",
    status: "new",
    received_at: "2026-01-01T00:00:00Z",
    recorded_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ReviewDetailCard", () => {
  it("shows rating both as text and stars, author, provider, status, and body", () => {
    render(<ReviewDetailCard review={review()} />);
    expect(screen.getByText("4/5")).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText("new")).toBeInTheDocument();
    expect(screen.getByText("Would recommend.")).toBeInTheDocument();
  });

  it("renders no body paragraph when the review has none", () => {
    render(<ReviewDetailCard review={review({ body: null })} />);
    expect(screen.queryByText("Would recommend.")).not.toBeInTheDocument();
  });
});
