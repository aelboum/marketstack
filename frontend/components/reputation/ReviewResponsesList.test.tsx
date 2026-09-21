import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ReviewResponsesList } from "./ReviewResponsesList";
import { ApiError } from "@/lib/api/errors";

const { listReviewResponsesMock } = vi.hoisted(() => ({ listReviewResponsesMock: vi.fn() }));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return { ...actual, listReviewResponses: listReviewResponsesMock };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

describe("ReviewResponsesList", () => {
  it("shows loading, then real responses", async () => {
    listReviewResponsesMock.mockResolvedValue({
      results: [{ id: "resp1", review_id: "rev1", body: "Thanks!", posted_by_user_id: "u1", created_at: "2026-01-01T00:00:00Z" }],
      hasMore: false,
    });
    render(<ReviewResponsesList tenantId="t1" reviewId="rev1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Thanks!")).toBeInTheDocument());
    expect(listReviewResponsesMock).toHaveBeenCalledWith("t1", "rev1", { limit: 25, offset: 0 });
  });

  it("shows an empty state with no responses", async () => {
    listReviewResponsesMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ReviewResponsesList tenantId="t1" reviewId="rev1" />);
    await waitFor(() => expect(screen.getByText("No responses yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listReviewResponsesMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<ReviewResponsesList tenantId="t1" reviewId="rev1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
