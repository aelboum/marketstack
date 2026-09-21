import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateReviewRequestForm } from "./CreateReviewRequestForm";
import { ApiError } from "@/lib/api/errors";

const { createReviewRequestMock } = vi.hoisted(() => ({ createReviewRequestMock: vi.fn() }));
vi.mock("@/lib/api/reputation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/reputation")>();
  return { ...actual, createReviewRequest: createReviewRequestMock };
});

const { listContactsMock } = vi.hoisted(() => ({ listContactsMock: vi.fn() }));
vi.mock("@/lib/api/crm", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/crm")>();
  return { ...actual, listContacts: listContactsMock };
});

describe("CreateReviewRequestForm", () => {
  it("disabled until a contact is chosen, then sends contact_id/message", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Ada", last_name: "Lovelace" }],
      hasMore: false,
    });
    createReviewRequestMock.mockResolvedValue({ id: "req1", status: "sent" });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    render(<CreateReviewRequestForm tenantId="t1" onSaved={onSaved} />);
    expect(screen.getByRole("button", { name: "Send review request" })).toBeDisabled();

    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Contact"), "c1");
    await user.type(screen.getByLabelText("Message"), "Thanks for stopping by!");
    await user.click(screen.getByRole("button", { name: "Send review request" }));

    await waitFor(() =>
      expect(createReviewRequestMock).toHaveBeenCalledWith("t1", {
        contact_id: "c1",
        message: "Thanks for stopping by!",
      }),
    );
    expect(onSaved).toHaveBeenCalledWith({ id: "req1", status: "sent" });
  });

  it("omits message when left blank", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Ada", last_name: "Lovelace" }],
      hasMore: false,
    });
    createReviewRequestMock.mockResolvedValue({ id: "req1" });
    const user = userEvent.setup();

    render(<CreateReviewRequestForm tenantId="t1" onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Contact"), "c1");
    await user.click(screen.getByRole("button", { name: "Send review request" }));

    await waitFor(() =>
      expect(createReviewRequestMock).toHaveBeenCalledWith("t1", {
        contact_id: "c1",
        message: undefined,
      }),
    );
  });

  it("blocks a message longer than the real 4000-character backend limit", async () => {
    listContactsMock.mockResolvedValue({ results: [], hasMore: false });
    const user = userEvent.setup();
    render(<CreateReviewRequestForm tenantId="t1" onSaved={vi.fn()} />);

    await user.click(screen.getByLabelText("Message"));
    await user.paste("x".repeat(4001));

    expect(screen.getByText(/4000 characters or fewer/)).toBeInTheDocument();
  });

  it("shows the backend's own validation error verbatim", async () => {
    listContactsMock.mockResolvedValue({
      results: [{ id: "c1", first_name: "Ada", last_name: "Lovelace" }],
      hasMore: false,
    });
    createReviewRequestMock.mockRejectedValue(
      new ApiError("validation", "channel must be one of ('email',).", { status: 400 }),
    );
    const user = userEvent.setup();

    render(<CreateReviewRequestForm tenantId="t1" onSaved={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Ada Lovelace")).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText("Contact"), "c1");
    await user.click(screen.getByRole("button", { name: "Send review request" }));

    await waitFor(() =>
      expect(screen.getByText("channel must be one of ('email',).")).toBeInTheDocument(),
    );
  });
});
