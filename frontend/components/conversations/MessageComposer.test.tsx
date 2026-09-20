import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MessageComposer } from "./MessageComposer";
import { ApiError } from "@/lib/api/errors";

const { createMessageMock, sendEmailMock, listTemplatesMock } = vi.hoisted(() => ({
  createMessageMock: vi.fn(),
  sendEmailMock: vi.fn(),
  listTemplatesMock: vi.fn(),
}));
vi.mock("@/lib/api/conversations", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/conversations")>();
  return {
    ...actual,
    createMessage: createMessageMock,
    sendEmail: sendEmailMock,
    listTemplates: listTemplatesMock,
  };
});

describe("MessageComposer", () => {
  it("email channel: defaults to the Send tab and sends via the real send-email operation", async () => {
    listTemplatesMock.mockResolvedValue([]);
    sendEmailMock.mockResolvedValue({ id: "m1" });
    const onSent = vi.fn();
    const user = userEvent.setup();

    render(<MessageComposer tenantId="t1" threadId="th1" channel="email" onSent={onSent} />);

    await user.type(screen.getByLabelText("To"), "a@example.com");
    await user.type(screen.getByLabelText("Subject"), "Hi");
    await user.type(screen.getByPlaceholderText("Email body…"), "Body text");
    // Two "Send email" buttons exist: the tab selector (already active by
    // default for an email-channel thread) and the form's own submit
    // button -- the submit button is the real one to click.
    const sendButtons = screen.getAllByRole("button", { name: "Send email" });
    await user.click(sendButtons[sendButtons.length - 1]);

    await waitFor(() =>
      expect(sendEmailMock).toHaveBeenCalledWith("t1", "th1", {
        to_email: "a@example.com",
        subject: "Hi",
        body: "Body text",
      }),
    );
    expect(onSent).toHaveBeenCalledOnce();
  });

  it("non-email channel: no Send tab exists, only Internal note, with an explanatory notice", async () => {
    listTemplatesMock.mockResolvedValue([]);
    render(<MessageComposer tenantId="t1" threadId="th1" channel="sms" onSent={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Send email" })).not.toBeInTheDocument();
    expect(screen.getByText(/no way to send a real sms message/)).toBeInTheDocument();
  });

  it("internal note: submits via createMessage with is_internal_note true, never sendEmail", async () => {
    listTemplatesMock.mockResolvedValue([]);
    createMessageMock.mockResolvedValue({ id: "m2" });
    const onSent = vi.fn();
    const user = userEvent.setup();

    render(<MessageComposer tenantId="t1" threadId="th1" channel="sms" onSent={onSent} />);

    await user.type(screen.getByPlaceholderText(/never sent to the contact/), "Called, no answer");
    await user.click(screen.getByRole("button", { name: "Add internal note" }));

    await waitFor(() =>
      expect(createMessageMock).toHaveBeenCalledWith("t1", "th1", {
        direction: "outbound",
        is_internal_note: true,
        body: "Called, no answer",
      }),
    );
    expect(sendEmailMock).not.toHaveBeenCalled();
    expect(onSent).toHaveBeenCalledOnce();
  });

  it("shows the backend error and does not clear the draft on failure", async () => {
    listTemplatesMock.mockResolvedValue([]);
    createMessageMock.mockRejectedValue(new ApiError("validation", "The request was invalid."));
    const user = userEvent.setup();

    render(<MessageComposer tenantId="t1" threadId="th1" channel="chat" onSent={vi.fn()} />);
    await user.type(screen.getByPlaceholderText(/never sent to the contact/), "Draft note");
    await user.click(screen.getByRole("button", { name: "Add internal note" }));

    await waitFor(() => expect(screen.getByText("The request was invalid.")).toBeInTheDocument());
    expect(screen.getByPlaceholderText(/never sent to the contact/)).toHaveValue("Draft note");
  });
});
