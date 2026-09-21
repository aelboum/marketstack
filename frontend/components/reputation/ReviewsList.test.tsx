import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewsList } from "./ReviewsList";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { listReviewsMock } = vi.hoisted(() => ({ listReviewsMock: vi.fn() }));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return { ...actual, listReviews: listReviewsMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function review(overrides: Record<string, unknown> = {}) {
  return {
    id: "rev1",
    tenant_id: "t1",
    review_request_id: null,
    provider: "manual",
    external_review_id: null,
    rating: 5,
    author_name: "Jane Doe",
    body: "Great service!",
    status: "new",
    received_at: "2026-01-01T00:00:00Z",
    recorded_by_user_id: "u1",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ReviewsList", () => {
  it("shows loading, then real reviews linked to their detail page", async () => {
    listReviewsMock.mockResolvedValue({ results: [review()], hasMore: false });
    render(<ReviewsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /5\/5/ })).toHaveAttribute(
      "href",
      "/t/t1/reputation/reviews/rev1",
    );
  });

  it("shows an empty state with no reviews", async () => {
    listReviewsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ReviewsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No reviews yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listReviewsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<ReviewsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("paginates via Previous/Next using limit/offset, never a fabricated total", async () => {
    listReviewsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => review({ id: `rev${i}`, author_name: `Author ${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<ReviewsList tenantId="t1" />);
    await waitFor(() => expect(listReviewsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }));

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(listReviewsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }));
  });
});
