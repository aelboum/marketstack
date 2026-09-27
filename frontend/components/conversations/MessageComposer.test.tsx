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
  it("email channel: defaults to the reply tab and sends via the real send-email operation", async () => {
    listTemplatesMock.mockResolvedValue([]);
    sendEmailMock.mockResolvedValue({ id: "m1" });
    const onSent = vi.fn();
    const user = userEvent.setup();

    render(<MessageComposer tenantId="t1" threadId="th1" channel="email" onSent={onSent} />);

    await user.type(screen.getByLabelText("Aan"), "a@example.com");
    await user.type(screen.getByLabelText("Onderwerp"), "Hi");
    await user.type(screen.getByPlaceholderText("Schrijf een antwoord…"), "Body text");
    // Two "Versturen" buttons exist: the tab selector's label differs
    // ("Antwoord") from the form's own submit button ("Versturen") --
    // click the submit button.
    await user.click(screen.getByRole("button", { name: "Versturen" }));

    await waitFor(() =>
      expect(sendEmailMock).toHaveBeenCalledWith("t1", "th1", {
        to_email: "a@example.com",
        subject: "Hi",
        body: "Body text",
      }),
    );
    expect(onSent).toHaveBeenCalledOnce();
  });

  it("non-email channel: no reply tab exists, only Internal note, with an explanatory notice", async () => {
    listTemplatesMock.mockResolvedValue([]);
    render(<MessageComposer tenantId="t1" threadId="th1" channel="sms" onSent={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Antwoord" })).not.toBeInTheDocument();
    expect(screen.getByText(/geen manier om een echt sms-bericht/)).toBeInTheDocument();
  });

  it("internal note: submits via createMessage with is_internal_note true, never sendEmail", async () => {
    listTemplatesMock.mockResolvedValue([]);
    createMessageMock.mockResolvedValue({ id: "m2" });
    const onSent = vi.fn();
    const user = userEvent.setup();

    render(<MessageComposer tenantId="t1" threadId="th1" channel="sms" onSent={onSent} />);

    await user.type(
      screen.getByPlaceholderText(/nooit verzonden naar de klant/),
      "Called, no answer",
    );
    await user.click(screen.getByRole("button", { name: "Notitie toevoegen" }));

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
    await user.type(screen.getByPlaceholderText(/nooit verzonden naar de klant/), "Draft note");
    await user.click(screen.getByRole("button", { name: "Notitie toevoegen" }));

    await waitFor(() => expect(screen.getByText("The request was invalid.")).toBeInTheDocument());
    expect(screen.getByPlaceholderText(/nooit verzonden naar de klant/)).toHaveValue("Draft note");
  });
});
