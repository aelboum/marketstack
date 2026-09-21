import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReviewDetailPage from "./page";
import { ApiError } from "@/lib/api/errors";

vi.mock("next/navigation", () => ({
  useParams: () => ({ tenantId: "tenant-1", reviewId: "rev1" }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: React.PropsWithChildren<{ href: string }>) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const { getReviewMock, listReviewResponsesMock, createReviewResponseMock } = vi.hoisted(() => ({
  getReviewMock: vi.fn(),
  listReviewResponsesMock: vi.fn(),
  createReviewResponseMock: vi.fn(),
}));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return {
    ...actual,
    getReview: getReviewMock,
    listReviewResponses: listReviewResponsesMock,
    createReviewResponse: createReviewResponseMock,
  };
});
vi.mock("@/lib/auth/session-context", () => ({
  useSession: () => ({ markSessionExpired: vi.fn() }),
}));

const REVIEW = {
  id: "rev1",
  tenant_id: "tenant-1",
  review_request_id: null,
  provider: "manual",
  external_review_id: null,
  rating: 5,
  author_name: "Jane Doe",
  body: "Excellent!",
  status: "new",
  received_at: "2026-01-01T00:00:00Z",
  recorded_by_user_id: "u1",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("ReviewDetailPage", () => {
  it("renders the real review once fetched by id", async () => {
    getReviewMock.mockResolvedValue(REVIEW);
    listReviewResponsesMock.mockResolvedValue({ results: [], hasMore: false });

    render(<ReviewDetailPage />);

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Review from Jane Doe" })).toBeInTheDocument(),
    );
    expect(getReviewMock).toHaveBeenCalledWith("tenant-1", "rev1");
  });

  it("posting a response shows confirmation and reloads the responses list", async () => {
    getReviewMock.mockResolvedValue(REVIEW);
    listReviewResponsesMock.mockResolvedValue({ results: [], hasMore: false });
    createReviewResponseMock.mockResolvedValue({ id: "resp1", body: "Thanks!" });
    const user = userEvent.setup();

    render(<ReviewDetailPage />);
    await waitFor(() => expect(screen.getByLabelText("Response")).toBeInTheDocument());

    await user.type(screen.getByLabelText("Response"), "Thanks!");
    await user.click(screen.getByRole("button", { name: "Post response" }));

    await waitFor(() => expect(createReviewResponseMock).toHaveBeenCalledWith("tenant-1", "rev1", { body: "Thanks!" }));
    expect(screen.getByText("Response posted.")).toBeInTheDocument();
    await waitFor(() => expect(listReviewResponsesMock).toHaveBeenCalledTimes(2));
  });

  it("shows the non-enumerating permission-denied state on 403/404", async () => {
    getReviewMock.mockRejectedValue(
      new ApiError("forbidden", "not found, or no access", { status: 404 }),
    );
    render(<ReviewDetailPage />);
    await waitFor(() =>
      expect(screen.getByText(/Not found, or you don't have access/)).toBeInTheDocument(),
    );
  });
});
