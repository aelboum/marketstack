import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ReviewRequestsList } from "./ReviewRequestsList";
import { ApiError } from "@/lib/api/errors";

const { listReviewRequestsMock, cancelReviewRequestMock } = vi.hoisted(() => ({
  listReviewRequestsMock: vi.fn(),
  cancelReviewRequestMock: vi.fn(),
}));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return {
    ...actual,
    listReviewRequests: listReviewRequestsMock,
    cancelReviewRequest: cancelReviewRequestMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

function reviewRequest(overrides: Record<string, unknown> = {}) {
  return {
    id: "req1",
    tenant_id: "t1",
    contact_id: "c1",
    channel: "email",
    status: "sent",
    failure_reason: null,
    requested_by_user_id: "u1",
    sent_at: "2026-01-01T00:00:00Z",
    cancelled_at: null,
    fulfilled_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ReviewRequestsList", () => {
  it("shows loading, then real review requests", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [reviewRequest()], hasMore: false });
    render(<ReviewRequestsList tenantId="t1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("sent")).toBeInTheDocument());
  });

  it("shows an empty state with no requests", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("No review requests yet")).toBeInTheDocument());
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    listReviewRequestsMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });

  it("shows the failure reason for a failed request", async () => {
    listReviewRequestsMock.mockResolvedValue({
      results: [reviewRequest({ status: "failed", failure_reason: "Invalid email address" })],
      hasMore: false,
    });
    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("Invalid email address")).toBeInTheDocument());
  });

  it("offers Cancel only for a request in 'sent' status", async () => {
    listReviewRequestsMock.mockResolvedValue({
      results: [reviewRequest({ id: "req2", status: "fulfilled" })],
      hasMore: false,
    });
    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByText("fulfilled")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });

  it("cancels a sent request after confirmation, then reloads the list", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [reviewRequest()], hasMore: false });
    cancelReviewRequestMock.mockResolvedValue(reviewRequest({ status: "cancelled" }));
    const user = userEvent.setup();

    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Cancel this review request?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel request" }));
    await waitFor(() => expect(cancelReviewRequestMock).toHaveBeenCalledWith("t1", "req1"));
    await waitFor(() => expect(listReviewRequestsMock).toHaveBeenCalledTimes(2));
  });

  it("paginates via Previous/Next using limit/offset", async () => {
    listReviewRequestsMock.mockResolvedValue({
      results: Array.from({ length: 25 }, (_, i) => reviewRequest({ id: `req${i}` })),
      hasMore: true,
    });
    const user = userEvent.setup();
    render(<ReviewRequestsList tenantId="t1" />);
    await waitFor(() =>
      expect(listReviewRequestsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 0 }),
    );

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() =>
      expect(listReviewRequestsMock).toHaveBeenCalledWith("t1", { limit: 25, offset: 25 }),
    );
  });
});
