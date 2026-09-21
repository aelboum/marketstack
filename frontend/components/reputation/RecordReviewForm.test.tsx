import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RecordReviewForm } from "./RecordReviewForm";
import { ApiError } from "@/lib/api/errors";

const { recordReviewMock, listReviewRequestsMock } = vi.hoisted(() => ({
  recordReviewMock: vi.fn(),
  listReviewRequestsMock: vi.fn(),
}));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return { ...actual, recordReview: recordReviewMock, listReviewRequests: listReviewRequestsMock };
});

describe("RecordReviewForm", () => {
  it("disabled until author name is filled, defaults rating to 5, sends provider 'manual'", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    recordReviewMock.mockResolvedValue({ id: "rev1", rating: 5 });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<RecordReviewForm tenantId="t1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Record review" })).toBeDisabled();

    await user.type(screen.getByLabelText("Author name"), "Jane Doe");
    await user.type(screen.getByLabelText("Review text"), "Loved it!");
    await user.click(screen.getByRole("button", { name: "Record review" }));

    await waitFor(() =>
      expect(recordReviewMock).toHaveBeenCalledWith("t1", {
        rating: 5,
        author_name: "Jane Doe",
        body: "Loved it!",
        review_request_id: undefined,
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "rev1", rating: 5 });
  });

  it("offers linking to a sent request, and sends its id when chosen", async () => {
    listReviewRequestsMock.mockResolvedValue({
      results: [
        { id: "req1", status: "sent", sent_at: "2026-01-01T00:00:00Z" },
        { id: "req2", status: "fulfilled", sent_at: "2026-01-02T00:00:00Z" },
      ],
      hasMore: false,
    });
    recordReviewMock.mockResolvedValue({ id: "rev1" });
    const user = userEvent.setup();

    render(<RecordReviewForm tenantId="t1" onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Link to a sent request/)).toBeInTheDocument());

    // Only the 'sent' request is offered, never the fulfilled one.
    const options = screen.getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    expect(options).toContain("req1");
    expect(options).not.toContain("req2");

    await user.type(screen.getByLabelText("Author name"), "Jo");
    await user.selectOptions(screen.getByLabelText(/Link to a sent request/), "req1");
    await user.click(screen.getByRole("button", { name: "Record review" }));

    await waitFor(() =>
      expect(recordReviewMock).toHaveBeenCalledWith(
        "t1",
        expect.objectContaining({ review_request_id: "req1" }),
      ),
    );
  });

  it("blocks an author name longer than the real 255-character backend limit", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    const user = userEvent.setup();
    render(<RecordReviewForm tenantId="t1" onSaved={vi.fn()} />);

    await user.click(screen.getByLabelText("Author name"));
    await user.paste("x".repeat(256));

    expect(screen.getByText(/255 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record review" })).toBeDisabled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    listReviewRequestsMock.mockResolvedValue({ results: [], hasMore: false });
    recordReviewMock.mockRejectedValue(
      new ApiError("validation", "rating must be an integer between 1 and 5.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<RecordReviewForm tenantId="t1" onSaved={vi.fn()} />);
    await user.type(screen.getByLabelText("Author name"), "Jane");
    await user.click(screen.getByRole("button", { name: "Record review" }));

    await waitFor(() =>
      expect(screen.getByText("rating must be an integer between 1 and 5.")).toBeInTheDocument(),
    );
  });
});
