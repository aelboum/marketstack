import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RespondToReviewForm } from "./RespondToReviewForm";
import { ApiError } from "@/lib/api/errors";

const { createReviewResponseMock } = vi.hoisted(() => ({ createReviewResponseMock: vi.fn() }));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return { ...actual, createReviewResponse: createReviewResponseMock };
});

describe("RespondToReviewForm", () => {
  it("disabled until a body is entered, then posts and clears the field", async () => {
    createReviewResponseMock.mockResolvedValue({ id: "resp1", body: "Thanks!" });
    const onSent = vi.fn();
    const user = userEvent.setup();

    render(<RespondToReviewForm tenantId="t1" reviewId="rev1" onSent={onSent} />);
    expect(screen.getByRole("button", { name: "Post response" })).toBeDisabled();

    await user.type(screen.getByLabelText("Response"), "Thanks!");
    await user.click(screen.getByRole("button", { name: "Post response" }));

    await waitFor(() =>
      expect(createReviewResponseMock).toHaveBeenCalledWith("t1", "rev1", { body: "Thanks!" }),
    );
    expect(onSent).toHaveBeenCalledWith({ id: "resp1", body: "Thanks!" });
    await waitFor(() => expect(screen.getByLabelText("Response")).toHaveValue(""));
  });

  it("blocks a response longer than the real 4000-character backend limit", async () => {
    const user = userEvent.setup();
    render(<RespondToReviewForm tenantId="t1" reviewId="rev1" onSent={vi.fn()} />);

    await user.click(screen.getByLabelText("Response"));
    await user.paste("x".repeat(4001));

    expect(screen.getByText(/4000 characters or fewer/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Post response" })).toBeDisabled();
  });

  it("shows the backend's own validation error verbatim", async () => {
    createReviewResponseMock.mockRejectedValue(
      new ApiError("validation", "body must not be empty.", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<RespondToReviewForm tenantId="t1" reviewId="rev1" onSent={vi.fn()} />);
    await user.type(screen.getByLabelText("Response"), "  ok  ");
    await user.click(screen.getByRole("button", { name: "Post response" }));

    await waitFor(() => expect(screen.getByText("body must not be empty.")).toBeInTheDocument());
  });
});
